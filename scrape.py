#!/usr/bin/env python3
"""Scrape Vietnamese finance news and summarize with LLM."""

import argparse
import json
import logging
import os
import ssl
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import cache_client
from llm_client import extract_and_summarize

load_dotenv()

log = logging.getLogger(__name__)


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    tickers: list = field(default_factory=list)
    thumbnail: Optional[dict] = None
    content: Optional[str] = None
    is_relevant: bool = True
    scraped_at: Optional[str] = None
    title_en: Optional[str] = None
    summary_en: Optional[str] = None
    content_en: Optional[str] = None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

VN_TZ = timezone(timedelta(hours=7))


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO 8601 string into a tz-aware datetime, or None if unparseable."""
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt


def _sanitize_published_at(value: Optional[str]) -> Optional[str]:
    """Drop a published_at that lies in the future.

    The LLM occasionally mis-extracts a date mentioned in the article body
    (e.g. a trading-week range like "25-29/6") as the publish date, yielding a
    future timestamp. A future date pins the article to the top of the
    newest-first feed forever and renders as "just now" on the frontend, so we
    discard it (→ null) rather than trust it. Past/parseable dates pass through
    unchanged; unparseable values are left as-is."""
    if not value:
        return value
    dt = _parse_iso(value)
    if dt is None:
        return value
    now = datetime.now(VN_TZ)
    if dt > now + timedelta(days=1):
        log.warning("Dropping future published_at=%s (now=%s)", value, now.isoformat())
        return None
    return value


def fetch_html(url: str, weak_ssl: bool = False) -> Optional[BeautifulSoup]:
    try:
        if weak_ssl:
            ctx = ssl.create_default_context()
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            resp = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True, verify=ctx)
        else:
            resp = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        log.error("fetch failed %s: %s", url, e)
        cache_client.record_error("scrape", str(e))
        return None


def get_article_links(url: str, domain: str, weak_ssl: bool = False,
                       selectors: str = "h2 a, h3 a, h4 a") -> list[dict]:
    """Generic link extraction from a category page."""
    soup = fetch_html(url, weak_ssl=weak_ssl)
    if not soup:
        return []

    articles = []
    for a in soup.select(selectors):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 15:
            continue
        if href.startswith("//"):
            href = f"https:{href}"
        elif not href.startswith("http"):
            href = f"https://{domain}{href}"
        if domain in href:
            articles.append({"title": title, "url": href})

    seen_urls = set()
    seen_titles = set()
    unique = []
    for a in articles:
        title_key = a["title"].strip().lower()
        if a["url"] in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(a["url"])
        seen_titles.add(title_key)
        unique.append(a)
    return unique


def _extract_thumbnail(soup: BeautifulSoup) -> Optional[dict]:
    """Extract thumbnail from Open Graph meta tags."""
    og_img = soup.find("meta", property="og:image")
    if not og_img or not og_img.get("content"):
        return None
    thumb = {"url": og_img["content"]}
    og_w = soup.find("meta", property="og:image:width")
    og_h = soup.find("meta", property="og:image:height")
    og_alt = soup.find("meta", property="og:image:alt")
    if og_w and og_w.get("content", "").isdigit():
        thumb["width"] = int(og_w["content"])
    if og_h and og_h.get("content", "").isdigit():
        thumb["height"] = int(og_h["content"])
    if og_alt and og_alt.get("content"):
        thumb["alt"] = og_alt["content"]
    return thumb


def _extract_next_data(soup: BeautifulSoup) -> Optional[dict]:
    """Extract __NEXT_DATA__ JSON from a Next.js page."""
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            return json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def get_page_data(url: str, weak_ssl: bool = False) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    """Fetch a page and return (visible_text, thumbnail_dict, published_at).

    published_at is None for generic pages — the LLM extracts the date from the
    text in that case. Next.js pages (get_page_data_nextjs) carry an authoritative
    date so they return it here."""
    soup = fetch_html(url, weak_ssl=weak_ssl)
    if not soup:
        return None, None, None
    thumbnail = _extract_thumbnail(soup)
    for tag in soup.select("script, style, nav, footer, header, aside"):
        tag.decompose()
    lines = [line for line in soup.get_text(separator="\n", strip=True).splitlines() if line.strip()]
    return "\n".join(lines), thumbnail, None


def get_page_data_nextjs(url: str, weak_ssl: bool = False) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    """Extract article text, thumbnail, and the authoritative publish date from a
    Next.js page's __NEXT_DATA__ JSON.

    The `date` field on the post is the source CMS's real publish timestamp; we
    return it so the caller can trust it over the LLM's guess (the LLM only sees
    the body text and can mistake a date mentioned in the prose for the publish
    date)."""
    soup = fetch_html(url, weak_ssl=weak_ssl)
    if not soup:
        return None, None, None

    thumbnail = _extract_thumbnail(soup)
    data = _extract_next_data(soup)
    if data:
        try:
            posts = data["props"]["pageProps"]["initialState"]["posts"]["posts"]["DETAIL"]["posts"]
            if posts:
                article = posts[0]
                content_html = article.get("content", "")
                if content_html:
                    content_soup = BeautifulSoup(content_html, "lxml")
                    lines = [l for l in content_soup.get_text(separator="\n", strip=True).splitlines() if l.strip()]
                    text = "\n".join(lines)
                    if not thumbnail and article.get("images"):
                        for img in article["images"]:
                            if img.get("imageUrl"):
                                thumbnail = {"url": img["imageUrl"]}
                                break
                    return text, thumbnail, article.get("date")
        except (KeyError, IndexError, TypeError):
            log.warning("Failed to parse __NEXT_DATA__ for %s", url)

    # Fallback to regular extraction
    return get_page_data(url, weak_ssl=weak_ssl)


SOURCES = {
    "cafef": {"url": "https://cafef.vn/thi-truong-chung-khoan.chn", "domain": "cafef.vn"},
    "vnexpress": {"url": "https://vnexpress.net/kinh-doanh", "domain": "vnexpress.net"},
    "tinnhanhchungkhoan": {"url": "https://tinnhanhchungkhoan.vn/chung-khoan/", "domain": "tinnhanhchungkhoan.vn"},
    "vietnambiz": {"url": "https://vietnambiz.vn/tai-chinh.htm", "domain": "vietnambiz.vn"},
    "vietstock": {"url": "https://vietstock.vn/chung-khoan.htm", "domain": "vietstock.vn"},
    "dantri": {"url": "https://dantri.com.vn/kinh-doanh.htm", "domain": "dantri.com.vn"},
    "thanhnien": {"url": "https://thanhnien.vn/kinh-te.htm", "domain": "thanhnien.vn"},
    "vneconomy": {"url": "https://vneconomy.vn/chung-khoan.htm", "domain": "vneconomy.vn"},
    "kinhtechungkhoan": {"url": "https://kinhtechungkhoan.vn/", "domain": "kinhtechungkhoan.vn"},
    "thoibaonganhang": {"url": "https://thoibaonganhang.vn/thi-truong-chung-khoan-24.html", "domain": "thoibaonganhang.vn"},
    "cafebiz": {"url": "https://cafebiz.vn/cau-chuyen-kinh-doanh/chung-khoan.chn", "domain": "cafebiz.vn"},
    "nguoiquansat": {"url": "https://nguoiquansat.vn/chung-khoan/", "domain": "nguoiquansat.vn"},
    "stockbiz": {
        "url": "https://stockbiz.vn/thi-truong",
        "domain": "stockbiz.vn",
        "selectors": 'a[href^="/tin-tuc/"]',
        "nextjs": True,
    },
}


def scrape_source(
    source_name: str,
    limit: int = 3,
    dry_run: bool = False,
    deadline: Optional[float] = None,
) -> list[Article]:
    """Scrape one source, returning the articles gathered.

    `deadline` is a time.monotonic() value after which no further article is
    started. It exists because asyncio.wait_for cannot cancel a thread: without a
    cooperative stop, a timed-out source kept scraping in the background and went
    on competing for the LLM lock, slowing every later cycle.
    """
    source = SOURCES[source_name]
    domain = source["domain"]
    weak_ssl = source.get("weak_ssl", False)

    t_source = time.monotonic()
    log.info("[%s] scraping started", source_name)

    selectors = source.get("selectors", "h2 a, h3 a, h4 a")
    is_nextjs = source.get("nextjs", False)

    articles_meta = get_article_links(source["url"], domain, weak_ssl=weak_ssl, selectors=selectors)
    log.info("[%s] found %d links, processing first %d", source_name, len(articles_meta), limit)

    results = []
    for i, meta in enumerate(articles_meta[:limit]):
        if deadline is not None and time.monotonic() >= deadline:
            log.warning("[%s] budget spent — stopping with %d/%d articles",
                        source_name, len(results), min(limit, len(articles_meta)))
            break
        url = meta["url"]
        n = f"{i + 1}/{limit}"
        log.info("[%s] [%s] %s", source_name, n, meta["title"][:70])

        cached = cache_client.get_article(url)
        if cached and cached.get("title_en"):
            log.info("[%s] [%s] cache hit", source_name, n)
            article = Article(
                title=cached.get("title", meta["title"]),
                url=url,
                source=domain,
                published_at=_sanitize_published_at(cached.get("published_at")),
                summary=cached.get("summary"),
                tickers=cached.get("tickers", []),
                thumbnail=cached.get("thumbnail"),
                content=cached.get("content"),
                is_relevant=cached.get("is_relevant", True),
                scraped_at=cached.get("scraped_at"),
                title_en=cached.get("title_en"),
                summary_en=cached.get("summary_en"),
                content_en=cached.get("content_en"),
            )
            results.append(article)
            continue
        elif cached:
            log.info("[%s] [%s] cache hit (legacy, missing EN — re-extracting)", source_name, n)

        if is_nextjs:
            page_text, thumbnail, page_published_at = get_page_data_nextjs(url, weak_ssl=weak_ssl)
        else:
            page_text, thumbnail, page_published_at = get_page_data(url, weak_ssl=weak_ssl)
        if not page_text:
            log.warning("[%s] [%s] page fetch failed — skipping", source_name, n)
            continue

        now = time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        parsed = extract_and_summarize(page_text, deadline=deadline)
        if parsed:
            # Prefer the source's authoritative date over the LLM's guess, then
            # drop it if it's in the future (LLM mis-extraction).
            published_at = _sanitize_published_at(page_published_at or parsed.get("published_at"))
            article = Article(
                title=parsed.get("title") or meta["title"],
                url=url,
                source=domain,
                published_at=published_at,
                summary=parsed.get("summary"),
                tickers=parsed.get("tickers", []),
                thumbnail=thumbnail,
                content=parsed.get("content"),
                is_relevant=parsed.get("is_relevant", True),
                scraped_at=now,
                title_en=parsed.get("title_en"),
                summary_en=parsed.get("summary_en"),
                content_en=parsed.get("content_en"),
            )
            if not dry_run:
                cache_client.set_article(
                    url, article.title, article.published_at, article.summary,
                    article.tickers, article.thumbnail, article.content,
                    article.is_relevant,
                    title_en=article.title_en,
                    summary_en=article.summary_en,
                    content_en=article.content_en,
                )
            results.append(article)
            log.info("[%s] [%s] done — published_at=%s", source_name, n, article.published_at)
        else:
            log.warning("[%s] [%s] LLM failed — skipping", source_name, n)

        # Publish progress so new articles are visible immediately, without
        # temporarily hiding the ones already cached.
        if results and not dry_run:
            _flush_news(source_name, results, merge=True)

    log.info("[%s] finished: %d/%d articles in %.1fs", source_name, len(results), limit, time.monotonic() - t_source)

    if results and not dry_run:
        _flush_news(source_name, results)

    return results


def _flush_news(source_name: str, results: list[Article], *, merge: bool = False) -> None:
    """Write results to the news:<source> cache list.

    merge=True unions the results with whatever is already cached (deduped by
    URL, fresh entries winning). Used for the incremental in-loop flush: a plain
    replace dropped the source to a single article and let it climb back over
    several minutes, so anything polling the API mid-refresh saw a nearly-empty
    source.

    merge=False replaces the list outright. Used for the final flush so the
    cache ends up authoritative and bounded — articles that fell off the
    source's front page are dropped instead of lingering until the key expires.
    """
    payload = [
        {
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
            "summary": a.summary,
            "tickers": a.tickers,
            "thumbnail": a.thumbnail,
            "content": a.content,
            "is_relevant": a.is_relevant,
            "scraped_at": a.scraped_at,
            "title_en": a.title_en,
            "summary_en": a.summary_en,
            "content_en": a.content_en,
        }
        for a in results
    ]
    if merge:
        fresh_urls = {item["url"] for item in payload}
        payload += [
            old for old in cache_client.get_news(source_name)
            if old.get("url") not in fresh_urls
        ]
    cache_client.set_news(source_name, payload)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape Vietnamese finance news.")
    parser.add_argument("--test", action="store_true", help="Test mode: first source, 3 articles")
    args = parser.parse_args()

    articles_per_source = int(os.environ.get("ARTICLES_PER_SOURCE", 30))
    max_total = int(os.environ.get("MAX_TOTAL_NEWS", 0))

    all_articles: list[Article] = []

    if args.test:
        first_source = next(iter(SOURCES))
        log.info("TEST MODE — scraping '%s' (3 articles)", first_source)
        all_articles.extend(scrape_source(first_source, limit=3))
    else:
        for source_name in SOURCES:
            all_articles.extend(scrape_source(source_name, limit=articles_per_source))
            if max_total and len(all_articles) >= max_total:
                log.info("Reached MAX_TOTAL_NEWS=%d, stopping", max_total)
                break

    log.info("TOTAL: %d articles scraped", len(all_articles))

    output = [asdict(a) for a in all_articles]
    Path("data").mkdir(exist_ok=True)
    filename = f"data/articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info("Saved to %s", filename)
