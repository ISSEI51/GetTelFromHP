import argparse
import csv
import json
import re
import sys
import time
from collections import deque
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

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
CONTEXT_WINDOW = 80
MAX_PARENT_DEPTH = 3


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
        response = session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT
        )
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


def load_keyword_bank(path: str) -> dict[str, set[str]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    primary_terms = {
        term.strip().lower() for term in data.get("primary_terms", []) if term.strip()
    }
    support_terms = {
        term.strip().lower() for term in data.get("support_terms", []) if term.strip()
    }
    if not primary_terms:
        raise ValueError("Keyword file must define at least one primary term")
    scan_terms = primary_terms | support_terms
    return {"primary_terms": primary_terms, "scan_terms": scan_terms}


def contains_keyword(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def normalize_phone_digits(tel: str) -> Optional[tuple[str, str]]:
    digits = re.sub(r"\D", "", tel)
    if digits.startswith("81") and len(digits) > 10:
        digits = "0" + digits[2:]
    if len(digits) < 10:
        return None
    if not digits.startswith("0"):
        return None
    cleaned_display = tel.strip()
    return digits, cleaned_display


def extract_phone_candidates(html: str, keywords: dict[str, set[str]]) -> list[tuple[str, bool]]:
    soup = BeautifulSoup(html, "html.parser")
    registry: dict[str, dict[str, object]] = {}
    order: list[str] = []

    def register(tel: str, is_hq: bool) -> None:
        prepared = normalize_phone_digits(tel)
        if not prepared:
            return
        digits, display = prepared
        if digits not in registry:
            registry[digits] = {"display": display, "is_hq": False}
            order.append(digits)
        if is_hq:
            registry[digits]["display"] = display
            registry[digits]["is_hq"] = True

    text = soup.get_text(" ", strip=True)
    for match in PHONE_REGEX.finditer(text):
        tel = match.group().strip()
        start, end = match.span()
        context = text[max(0, start - CONTEXT_WINDOW) : min(len(text), end + CONTEXT_WINDOW)]
        is_hq = contains_keyword(context, keywords["primary_terms"])
        register(tel, is_hq)

    def iterate_nodes():
        for node in soup.find_all(
            string=lambda value: bool(value and contains_keyword(value, keywords["scan_terms"]))
        ):
            parent = node.parent
            depth = 0
            while parent and depth < MAX_PARENT_DEPTH:
                segment = parent.get_text(" ", strip=True)
                if not segment:
                    break
                yield segment
                parent = parent.parent
                depth += 1

    for segment in iterate_nodes():
        is_hq_segment = contains_keyword(segment, keywords["primary_terms"])
        for match in PHONE_REGEX.finditer(segment):
            register(match.group().strip(), is_hq_segment)

    results: list[tuple[str, bool]] = []
    for key in order:
        entry = registry[key]
        results.append((entry["display"], bool(entry["is_hq"])))
    return results


def crawl_for_hq_phone(
    start_url: str,
    keywords: dict[str, set[str]],
    max_pages: int,
    delay: float,
) -> Optional[str]:
    try:
        start = normalize_url(start_url)
    except ValueError:
        log(f"Skipping invalid URL: {start_url}")
        return None

    target_domain = urlparse(start).netloc
    session = requests.Session()
    queue = deque([start])
    visited = set()
    hq_numbers: dict[str, str] = {}
    all_numbers: dict[str, str] = {}

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

        for tel, is_hq in extract_phone_candidates(html, keywords):
            normalized = normalize_phone_digits(tel)
            if not normalized:
                continue
            digits, display = normalized
            if digits not in all_numbers:
                all_numbers[digits] = display
            if is_hq and digits not in hq_numbers:
                hq_numbers[digits] = display

        if hq_numbers:
            chosen = next(iter(hq_numbers.values()))
            log(f"  Found HQ number for {target_domain}: {chosen}")
            return chosen

        for link in extract_links(html, current):
            if same_domain(link, target_domain) and link not in visited:
                queue.append(link)

        if delay:
            time.sleep(delay)

    if len(all_numbers) == 1:
        only_tel = next(iter(all_numbers.values()))
        log(f"  Unique number detected for {target_domain}: {only_tel}")
        return only_tel

    log(f"  No HQ number identified for {target_domain}")
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
        writer = csv.DictWriter(handle, fieldnames=["url", "hq_tel"])
        writer.writeheader()
        for url, tel in rows:
            writer.writerow({"url": url, "hq_tel": tel or ""})


def run(
    input_csv: str,
    output_csv: str,
    keyword_path: str,
    max_pages: int,
    delay: float,
) -> None:
    keywords = load_keyword_bank(keyword_path)
    results = []
    for url in read_urls(input_csv):
        log(f"Start HQ crawl for {url}")
        tel = crawl_for_hq_phone(url, keywords, max_pages=max_pages, delay=delay)
        if not tel:
            log(f"No HQ phone number found for {url}")
        results.append((url, tel))
    write_results(results, output_csv)
    log(f"Wrote HQ-only results to {output_csv}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract HQ phone numbers from company homepages"
    )
    parser.add_argument("input", help="Input CSV file with a 'url' column")
    parser.add_argument("output", help="Output CSV path")
    parser.add_argument(
        "--keywords",
        default="hq_keywords.json",
        help="Path to the HQ keyword JSON file (default: hq_keywords.json)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=120,
        help="Maximum number of pages to crawl per domain (default: 120)",
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
        run(args.input, args.output, args.keywords, args.max_pages, args.delay)
    except Exception as exc:  # pragma: no cover
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
