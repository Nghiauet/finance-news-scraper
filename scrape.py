#!/usr/bin/env python3
"""Scrape Vietnamese finance news and summarize with LLM."""

import argparse
import json
import ssl
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import cache_client
from llm_client import extract_and_summarize

load_dotenv()


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}


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
        print(f"  [ERROR] fetch {url}: {e}")
        return None


def get_article_links(url: str, domain: str, weak_ssl: bool = False) -> list[dict]:
    """Generic link extraction from a category page."""
    soup = fetch_html(url, weak_ssl=weak_ssl)
    if not soup:
        return []

    articles = []
    for a in soup.select("h2 a, h3 a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 15:
            continue
        if not href.startswith("http"):
            href = f"https://{domain}{href}"
        if domain in href:
            articles.append({"title": title, "url": href})

    seen = set()
    return [a for a in articles if not (a["url"] in seen or seen.add(a["url"]))]


def get_page_text(url: str, weak_ssl: bool = False) -> Optional[str]:
    """Fetch a page and return its visible text content."""
    soup = fetch_html(url, weak_ssl=weak_ssl)
    if not soup:
        return None
    for tag in soup.select("script, style, nav, footer, header, aside"):
        tag.decompose()
    lines = [line for line in soup.get_text(separator="\n", strip=True).splitlines() if line.strip()]
    return "\n".join(lines)


SOURCES = {
    "cafef": {"url": "https://cafef.vn/thi-truong-chung-khoan.chn", "domain": "cafef.vn"},
    "vnexpress": {"url": "https://vnexpress.net/kinh-doanh", "domain": "vnexpress.net"},
    "tinnhanhchungkhoan": {"url": "https://tinnhanhchungkhoan.vn/chung-khoan/", "domain": "tinnhanhchungkhoan.vn"},
    "ndh": {"url": "https://ndh.vn/chung-khoan.htm", "domain": "ndh.vn", "weak_ssl": True},
    "baodautu": {"url": "https://baodautu.vn/chung-khoan-d1.html", "domain": "baodautu.vn"},
    "vietnambiz": {"url": "https://vietnambiz.vn/tai-chinh.htm", "domain": "vietnambiz.vn"},
    "vietstock": {"url": "https://vietstock.vn/chung-khoan.htm", "domain": "vietstock.vn"},
    "dantri": {"url": "https://dantri.com.vn/kinh-doanh.htm", "domain": "dantri.com.vn"},
    "tuoitre": {"url": "https://tuoitre.vn/kinh-te.htm", "domain": "tuoitre.vn"},
    "thanhnien": {"url": "https://thanhnien.vn/kinh-te.htm", "domain": "thanhnien.vn"},
}


def scrape_source(source_name: str, limit: int = 3) -> list[Article]:
    source = SOURCES[source_name]
    domain = source["domain"]
    weak_ssl = source.get("weak_ssl", False)

    print(f"\n{'='*60}")
    print(f"Scraping: {source_name}")
    print(f"{'='*60}")

    articles_meta = get_article_links(source["url"], domain, weak_ssl=weak_ssl)
    print(f"  Found {len(articles_meta)} articles, processing first {limit}...")

    results = []
    for i, meta in enumerate(articles_meta[:limit]):
        url = meta["url"]
        print(f"  -> {meta['title'][:60]}...")

        cached = cache_client.get_article(url)
        if cached:
            print(f"     [CACHE] Article hit")
            article = Article(
                title=cached.get("title", meta["title"]),
                url=url,
                source=domain,
                published_at=cached.get("published_at"),
                summary=cached.get("summary"),
            )
            print(f"     Summary: {article.summary}")
            results.append(article)
            continue

        page_text = get_page_text(url, weak_ssl=weak_ssl)
        if not page_text:
            print(f"     [SKIP] could not fetch page")
            continue

        parsed = extract_and_summarize(page_text)
        if parsed:
            article = Article(
                title=parsed.get("title") or meta["title"],
                url=url,
                source=domain,
                published_at=parsed.get("published_at"),
                summary=parsed.get("summary"),
            )
            cache_client.set_article(url, article.title, article.published_at, article.summary)
            results.append(article)
            print(f"     [OK] summarized")
            print(f"     Summary: {article.summary}")
        else:
            print(f"     [SKIP] LLM failed")

        if i < len(articles_meta[:limit]) - 1:
            time.sleep(1)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Vietnamese finance news.")
    parser.add_argument("--test", action="store_true", help="Test mode: first source, 3 articles")
    args = parser.parse_args()

    all_articles: list[Article] = []

    if args.test:
        first_source = next(iter(SOURCES))
        print(f"[TEST MODE] Scraping only '{first_source}' — first 3 articles")
        all_articles.extend(scrape_source(first_source, limit=3))
    else:
        for source_name in SOURCES:
            all_articles.extend(scrape_source(source_name, limit=2))

    print(f"\n\n{'='*60}")
    print(f"RESULTS: {len(all_articles)} articles")
    print(f"{'='*60}")

    for art in all_articles:
        print(f"\n{'─'*60}")
        print(f"Title  : {art.title}")
        print(f"Source : {art.source}")
        print(f"Date   : {art.published_at}")
        print(f"URL    : {art.url}")
        print(f"Summary: {art.summary}")

    output = [asdict(a) for a in all_articles]
    Path("data").mkdir(exist_ok=True)
    filename = f"data/articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {filename}")
