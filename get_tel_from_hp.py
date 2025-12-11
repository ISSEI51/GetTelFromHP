import argparse
import csv
import re
import sys
import time
from collections import deque
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Matches Japanese phone numbers such as 03-1234-5678, 0120-123-456, +81-3-1234-5678, etc.
PHONE_REGEX = re.compile(
    r"""
    (?:\+?81[-\s]?)?               # optional country code
    (?:0\d{1,4}|[1-9]\d{1,3})      # area code starting digit
    [-\s]?
    \d{1,4}
    [-\s]?
    \d{3,4}
    """,
    re.VERBOSE,
)

USER_AGENT = "Mozilla/5.0 (compatible; TelCrawler/1.0; +https://example.com)"
DEFAULT_TIMEOUT = 10
GREEN = "\033[92m"
RESET = "\033[0m"


def log(message: str) -> None:
    print(f"[INFO] {message}")


def normalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    if not parsed.netloc:
        raise ValueError(f"URL missing host: {raw_url}")
    scheme = parsed.scheme or "https"
    normalized = parsed._replace(scheme=scheme)
    return normalized.geturl()


def same_domain(url: str, domain: str) -> bool:
    return urlparse(url).netloc == domain


def fetch(session: requests.Session, url: str) -> Optional[str]:
    try:
        response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", ""):
            return None
        response.encoding = response.encoding or response.apparent_encoding
        return response.text
    except requests.RequestException:
        return None


def extract_links(html: str, base_url: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("a", href=True):
        joined = urljoin(base_url, tag["href"])
        parsed = urlparse(joined)
        if parsed.scheme in {"http", "https"}:
            yield parsed.geturl()


def find_phone_number(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    for match in PHONE_REGEX.findall(text):
        digits = re.sub(r"\D", "", match)
        if len(digits) >= 9:
            return match
    return None


def crawl_for_phone(start_url: str, max_pages: int, delay: float) -> Optional[str]:
    try:
        start = normalize_url(start_url)
    except ValueError:
        log(f"Skipping invalid URL: {start_url}")
        return None

    target_domain = urlparse(start).netloc
    session = requests.Session()
    queue = deque([start])
    visited = set()

    while queue and len(visited) < max_pages:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        log(f"Visiting {current}")
        html = fetch(session, current)
        if not html:
            log(f"  No HTML content, skipping: {current}")
            continue

        tel = find_phone_number(html)
        if tel:
            print(f"{GREEN}[FOUND]{RESET} {target_domain} {tel}")
            return tel

        for link in extract_links(html, current):
            if same_domain(link, target_domain) and link not in visited:
                queue.append(link)

        if delay:
            time.sleep(delay)

    return None


def read_urls(csv_path: str) -> Iterable[str]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if "url" not in reader.fieldnames:
            raise ValueError("Input CSV must have a 'url' column")
        for row in reader:
            url = row.get("url", "").strip()
            if url:
                yield url


def write_results(rows: Iterable[tuple[str, Optional[str]]], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["url", "tel"])
        writer.writeheader()
        for url, tel in rows:
            writer.writerow({"url": url, "tel": tel or ""})


def run(input_csv: str, output_csv: str, max_pages: int, delay: float) -> None:
    results = []
    for url in read_urls(input_csv):
        log(f"Start crawling for {url}")
        tel = crawl_for_phone(url, max_pages=max_pages, delay=delay)
        if not tel:
            log(f"No phone number found for {url}")
        results.append((url, tel))
    write_results(results, output_csv)
    log(f"Wrote results to {output_csv}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract phone numbers from company homepages")
    parser.add_argument("input", help="Input CSV file with a 'url' column")
    parser.add_argument("output", help="Output CSV path")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Maximum number of pages to crawl per domain (default: 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay in seconds between requests (default: 0)",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args.input, args.output, args.max_pages, args.delay)
    except Exception as exc:  # pragma: no cover
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
