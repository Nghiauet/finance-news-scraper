#!/usr/bin/env python3
"""Scrape Vietnamese finance news and summarize with LLM."""

import argparse
import json
import logging
import os
import re
import ssl
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
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


def fetch_page(url: str, weak_ssl: bool = False) -> Optional[str]:
    """Fetch a URL and return its HTML, or None on any failure."""
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
        return resp.text
    except Exception as e:
        log.error("fetch failed %s: %s", url, e)
        cache_client.record_error("scrape", str(e))
        return None


def fetch_html(url: str, weak_ssl: bool = False) -> Optional[BeautifulSoup]:
    html = fetch_page(url, weak_ssl=weak_ssl)
    return BeautifulSoup(html, "lxml") if html is not None else None


def _looks_like_article_url(url: str) -> bool:
    """True for article URLs, False for section/menu pages.

    Category pages put menu links inside h2/h3 too, and their anchor text is
    long enough to pass the title-length check. Those pages then went to the
    LLM, which "summarised" whatever headline happened to be on the listing
    and published it under the section URL (vneconomy.vn/cong-nghe-startup.htm,
    kinhtechungkhoan.vn/bao-cao-phan-tich, ...). Vietnamese news URLs carry
    either a long slug or a numeric article id; section URLs have neither.
    """
    path = urlparse(url).path
    if re.search(r"\d{6,}", path):
        return True
    return any(seg.count("-") >= 4 for seg in path.split("/"))


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
        # urljoin handles absolute, protocol-relative, root-relative and
        # path-relative hrefs alike. The old f"https://{domain}{href}" silently
        # produced "https://domain.vnsome-slug" for any href without a leading
        # slash, which then failed DNS — kinhtechungkhoan lost 17 of 20 links.
        href = urljoin(url, href)
        if domain in href and _looks_like_article_url(href):
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


# Where Vietnamese news CMSes put the publish time, most specific first.
_DATE_META_ATTRS = [
    {"property": "article:published_time"},
    {"name": "article:published_time"},
    {"itemprop": "datePublished"},
    {"name": "pubdate"},
    {"name": "publishdate"},
    {"property": "og:article:published_time"},
]
_LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_ISO_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}:\d{2}(?::\d{2})?)(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?)?$"
)
_SLASH_DATE_RE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?)?$"
)


def _normalize_date(raw: str) -> Optional[str]:
    """Turn a CMS date string into ISO 8601 +07:00, or None if unrecognised.

    Seen in the wild: "2026-09-24T08:07:07+07:00", "2026-09-24T00:05:00" (no
    zone — VN sites publish local time), "2026-09-24T09:06:00.000 +07:00",
    "9/24/2026 8:04:01 AM" (US order, always with AM/PM) and "24/09/2026"
    (VN order)."""
    s = (raw or "").strip()
    m = _ISO_DATE_RE.match(s)
    if m:
        day, clock, tz = m.groups()
        clock = clock or "00:00:00"
        if clock.count(":") == 1:
            clock += ":00"
        if len(clock.split(":")[0]) == 1:
            clock = "0" + clock
        if tz is None:
            tz = "+07:00"
        elif tz == "Z":
            tz = "+00:00"
        elif ":" not in tz:
            tz = f"{tz[:3]}:{tz[3:]}"
        try:
            dt = datetime.fromisoformat(f"{day}T{clock}{tz}")
        except ValueError:
            return None
        return dt.astimezone(VN_TZ).strftime("%Y-%m-%dT%H:%M:%S+07:00")
    m = _SLASH_DATE_RE.match(s)
    if m:
        a, b, year, hh, mm, ss, ampm = m.groups()
        a, b = int(a), int(b)
        # AM/PM marks the US month-first layout; otherwise day comes first.
        if a > 12 or (b <= 12 and not ampm):
            day_n, month = a, b
        else:
            month, day_n = a, b
        hour = int(hh or 0)
        if ampm:
            hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
        try:
            dt = datetime(int(year), month, day_n, hour, int(mm or 0), int(ss or 0), tzinfo=VN_TZ)
        except ValueError:
            return None
        return dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    return None


def _extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    """The CMS's own publish time from meta tags or JSON-LD, if the page has one.

    This beats the LLM's reading of the body, which can pick up a date the
    article merely mentions (see _sanitize_published_at)."""
    for attrs in _DATE_META_ATTRS:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            value = _normalize_date(tag["content"])
            if value:
                return value
    for script in soup.find_all("script", type="application/ld+json"):
        m = _LD_DATE_RE.search(script.string or "")
        if m:
            value = _normalize_date(m.group(1))
            if value:
                return value
    return None


# Below this, trafilatura probably missed the body (video/gallery layouts) and
# the whole-page text is the better bet.
_MIN_MAIN_TEXT = 300


def _extract_main_text(html: str, soup: BeautifulSoup) -> str:
    """Article body without menus, sidebars and related-article lists.

    The whole-page text was 30-70% boilerplate: other articles' headlines that
    the LLM could mistake for this story, plus tokens paid for on every call."""
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    except Exception as e:
        log.warning("trafilatura failed: %s", e)
        text = ""
    if len(text) < _MIN_MAIN_TEXT:
        for tag in soup.select("script, style, nav, footer, header, aside"):
            tag.decompose()
        return "\n".join(line for line in soup.get_text(separator="\n", strip=True).splitlines() if line.strip())
    # trafilatura often drops the headline; the LLM needs it for context.
    og_title = soup.find("meta", property="og:title")
    headline = (og_title.get("content") or "").strip() if og_title else ""
    if headline and headline not in text[:500]:
        text = f"{headline}\n{text}"
    return text


def get_page_data(url: str, weak_ssl: bool = False) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    """Fetch a page and return (article_text, thumbnail_dict, published_at).

    published_at comes from the page's metadata when present; it is None
    otherwise and the LLM's extraction is used instead."""
    html = fetch_page(url, weak_ssl=weak_ssl)
    if html is None:
        return None, None, None
    soup = BeautifulSoup(html, "lxml")
    thumbnail = _extract_thumbnail(soup)
    published_at = _extract_published_at(soup)
    return _extract_main_text(html, soup), thumbnail, published_at


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
    # The bare homepage went client-side rendered and serves no article links;
    # /chung-khoan is still server-rendered and topically narrower.
    "kinhtechungkhoan": {"url": "https://kinhtechungkhoan.vn/chung-khoan", "domain": "kinhtechungkhoan.vn"},
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

# Shorter than this after extraction means a paywall, video or error page —
# not worth an LLM call.
_MIN_ARTICLE_TEXT = 200


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
        if len(page_text) < _MIN_ARTICLE_TEXT:
            log.warning("[%s] [%s] only %d chars of text — skipping", source_name, n, len(page_text))
            continue

        now = cache_client.vn_now_iso()
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
