#!/usr/bin/env python3
"""
Quick script to extract content from Vietnamese finance news sources.
Supported: cafef.vn, vnexpress.net, tinnhanhchungkhoan.vn,
           ndh.vn, baodautu.vn, vietnambiz.vn, vietstock.vn,
           dantri.com.vn, tuoitre.vn, thanhnien.vn
"""

import argparse
import json
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import cache_client
from llm_client import summarize

load_dotenv()


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    content: str
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
            resp = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True, verify=ctx)
        else:
            resp = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [ERROR] fetch {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Cafef.vn
# ---------------------------------------------------------------------------

def get_cafef_list(category_url: str = "https://cafef.vn/thi-truong-chung-khoan.chn") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://cafef.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_cafef(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1.title, h1.detail-title, h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("span.pdate, time, .time")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.detail-content, div#mainContent, article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="cafef.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# VnExpress
# ---------------------------------------------------------------------------

def get_vnexpress_list(category_url: str = "https://vnexpress.net/kinh-doanh") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3.title-news a, h2.title-news a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_vnexpress(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1.title-detail, h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("span.date, .date")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("article.fck_detail, div.fck_detail")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="vnexpress.net", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# TinNhanhChungKhoan.vn
# ---------------------------------------------------------------------------

def get_tnnck_list(category_url: str = "https://tinnhanhchungkhoan.vn/chung-khoan/") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a, .story__headline a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://tinnhanhchungkhoan.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_tnnck(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date-time, .time-public")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.detail__content, div.article__body, article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="tinnhanhchungkhoan.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# NDH.vn
# ---------------------------------------------------------------------------

def get_ndh_list(category_url: str = "https://ndh.vn/chung-khoan.htm") -> list[dict]:
    soup = fetch_html(category_url, weak_ssl=True)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a, .story-title a, .item-title a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://ndh.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_ndh(url: str) -> Optional[Article]:
    soup = fetch_html(url, weak_ssl=True)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date, .post-date, span.time")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.detail-content, div.post-content, div.entry-content, article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="ndh.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# BaoDauTu.vn
# ---------------------------------------------------------------------------

def get_baodautu_list(category_url: str = "https://baodautu.vn/chung-khoan-d1.html") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    article_pattern = re.compile(r"https://baodautu\.vn/.+-d\d+\.html$")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not href.startswith("http"):
            href = "https://baodautu.vn" + href
        if article_pattern.match(href) and len(title) > 20:
            articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_baodautu(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date, .post-time, .article-date")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.detail-content, div.article-content, div#mainContent, article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="baodautu.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# VietnamBiz.vn
# ---------------------------------------------------------------------------

def get_vietnambiz_list(category_url: str = "https://vietnambiz.vn/tai-chinh.htm") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a, .story__headline a, .article__title a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://vietnambiz.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_vietnambiz(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .time, .date, .post-time")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.vnbcbc-body, div.article-body-content, div.detail-content, div.article-body")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="vietnambiz.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# Vietstock.vn
# ---------------------------------------------------------------------------

def get_vietstock_list(category_url: str = "https://vietstock.vn/chung-khoan.htm") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    article_pattern = re.compile(r"https://vietstock\.vn/\d{4}/\d{2}/.+\.htm$")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not href.startswith("http"):
            href = "https://vietstock.vn" + href
        if article_pattern.match(href) and len(title) > 15:
            articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_vietstock(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date, .post-date, .news-date")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div#vst_detail, div.content-detail, div.article-content, div.fck")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="vietstock.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# DanTri.com.vn
# ---------------------------------------------------------------------------

def get_dantri_list(category_url: str = "https://dantri.com.vn/kinh-doanh.htm") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a, .article-title a, .news-title a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://dantri.com.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_dantri(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date, .author-date time, span.date")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.singular-content, div.article-content, div[data-role='content'], article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="dantri.com.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# TuoiTre.vn
# ---------------------------------------------------------------------------

def get_tuoitre_list(category_url: str = "https://tuoitre.vn/kinh-te.htm") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a, .title-news a, .news-item__title a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://tuoitre.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_tuoitre(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date, .article-publish time")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div#main-detail-body, div.detail-content, div[id='article-body'], article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="tuoitre.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# ThanhNien.vn
# ---------------------------------------------------------------------------

def get_thanhnien_list(category_url: str = "https://thanhnien.vn/kinh-te.htm") -> list[dict]:
    soup = fetch_html(category_url)
    if not soup:
        return []

    articles = []
    for a in soup.select("h3 a, h2 a, .story__title a, .article__title a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title:
            continue
        if not href.startswith("http"):
            href = "https://thanhnien.vn" + href
        articles.append({"title": title, "url": href})

    seen = set()
    result = []
    for art in articles:
        if art["url"] not in seen:
            seen.add(art["url"])
            result.append(art)
    return result[:10]


def extract_thanhnien(url: str) -> Optional[Article]:
    soup = fetch_html(url)
    if not soup:
        return None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    date_tag = soup.select_one("time, .date, .article__header--publisheddate")
    published_at = date_tag.get_text(strip=True) if date_tag else None

    body = soup.select_one("div.detail-content, div#abody, div.article__body, article")
    if not body:
        return None

    paragraphs = [p.get_text(strip=True) for p in body.select("p") if p.get_text(strip=True)]
    content = "\n\n".join(paragraphs)

    return Article(title=title, url=url, source="thanhnien.vn", published_at=published_at, content=content)


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES = {
    "cafef": {
        "list_fn": get_cafef_list,
        "extract_fn": extract_cafef,
        "default_url": "https://cafef.vn/thi-truong-chung-khoan.chn",
    },
    "vnexpress": {
        "list_fn": get_vnexpress_list,
        "extract_fn": extract_vnexpress,
        "default_url": "https://vnexpress.net/kinh-doanh",
    },
    "tinnhanhchungkhoan": {
        "list_fn": get_tnnck_list,
        "extract_fn": extract_tnnck,
        "default_url": "https://tinnhanhchungkhoan.vn/chung-khoan/",
    },
    "ndh": {
        "list_fn": get_ndh_list,
        "extract_fn": extract_ndh,
        "default_url": "https://ndh.vn/chung-khoan.htm",
    },
    "baodautu": {
        "list_fn": get_baodautu_list,
        "extract_fn": extract_baodautu,
        "default_url": "https://baodautu.vn/chung-khoan-d1.html",
    },
    "vietnambiz": {
        "list_fn": get_vietnambiz_list,
        "extract_fn": extract_vietnambiz,
        "default_url": "https://vietnambiz.vn/tai-chinh.htm",
    },
    "vietstock": {
        "list_fn": get_vietstock_list,
        "extract_fn": extract_vietstock,
        "default_url": "https://vietstock.vn/chung-khoan.htm",
    },
    "dantri": {
        "list_fn": get_dantri_list,
        "extract_fn": extract_dantri,
        "default_url": "https://dantri.com.vn/kinh-doanh.htm",
    },
    "tuoitre": {
        "list_fn": get_tuoitre_list,
        "extract_fn": extract_tuoitre,
        "default_url": "https://tuoitre.vn/kinh-te.htm",
    },
    "thanhnien": {
        "list_fn": get_thanhnien_list,
        "extract_fn": extract_thanhnien,
        "default_url": "https://thanhnien.vn/kinh-te.htm",
    },
}


def scrape_source(source_name: str, limit: int = 3) -> list[Article]:
    source = SOURCES[source_name]
    print(f"\n{'='*60}")
    print(f"Scraping: {source_name}")
    print(f"{'='*60}")

    articles_meta = source["list_fn"](source["default_url"])
    print(f"  Found {len(articles_meta)} articles, processing first {limit}...")

    results = []
    for i, meta in enumerate(articles_meta[:limit]):
        url = meta["url"]
        print(f"  -> {meta['title'][:60]}...")

        # Check article content cache first
        cached_content = cache_client.get_article(url)
        if cached_content:
            print(f"     [CACHE] Article hit")
            article = Article(
                title=meta["title"],
                url=url,
                source=source_name,
                published_at=None,
                content=cached_content,
            )
        else:
            article = source["extract_fn"](url)
            if article:
                cache_client.set_article(url, article.content)

        if article:
            article.summary = summarize(article.content)
            results.append(article)
            print(f"     [OK] {len(article.content)} chars extracted")
        else:
            print(f"     [SKIP] could not extract content")

        if i < len(articles_meta[:limit]) - 1:
            time.sleep(1)

    return results


def print_article(article: Article):
    print(f"\n{'─'*60}")
    print(f"Title   : {article.title}")
    print(f"Source  : {article.source}")
    print(f"Date    : {article.published_at}")
    print(f"URL     : {article.url}")
    print(f"Content preview:")
    preview = article.content[:500] + "..." if len(article.content) > 500 else article.content
    print(preview)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Vietnamese finance news.")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: scrape only the first source with 3 articles",
    )
    args = parser.parse_args()

    all_articles: list[Article] = []

    if args.test:
        first_source = next(iter(SOURCES))
        print(f"[TEST MODE] Scraping only '{first_source}' — first 3 articles")
        articles = scrape_source(first_source, limit=3)
        all_articles.extend(articles)
    else:
        for source_name in SOURCES:
            articles = scrape_source(source_name, limit=2)
            all_articles.extend(articles)

    print(f"\n\n{'='*60}")
    print(f"RESULTS: {len(all_articles)} articles extracted")
    print(f"{'='*60}")

    for art in all_articles:
        print_article(art)

    output = [
        {
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
            "content": a.content,
            "summary": a.summary,
        }
        for a in all_articles
    ]

    Path("data").mkdir(exist_ok=True)
    filename = f"data/articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {filename}")
