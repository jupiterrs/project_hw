#!/usr/bin/env python3
"""Scrape AIME problems from AoPS wiki (2019-2025).

Two-phase approach:
1. Download all pages to local HTML files (retry on Cloudflare)
2. Parse from local files (reliable)
"""
import re, json, time, sys, os
from pathlib import Path
import subprocess

DATA_DIR = Path(__file__).parent / "sft-data"
CACHE_DIR = Path("/tmp/aops_cache")

CURL_CMD = [
    'curl', '-sL',
    '-H', 'User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0',
    '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    '-H', 'Accept-Language: en-US,en;q=0.5',
    '-c', '/tmp/aops_cookies.txt',
]

YEARS = range(2019, 2026)
CONTESTS = ['I', 'II']


def fetch_page(url, retries=3):
    for attempt in range(retries):
        r = subprocess.run(CURL_CMD + [url], capture_output=True, text=True, timeout=30)
        html = r.stdout
        if html and 'Cloudflare' not in html and 'Attention Required' not in html and len(html) > 5000:
            return html
        time.sleep(2)
    return None


def download_all():
    """Phase 1: Download all pages."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for year in YEARS:
        for contest in CONTESTS:
            # Download problems page
            prob_file = CACHE_DIR / f"{year}_AIME_{contest}_Problems.html"
            if not prob_file.exists() or prob_file.stat().st_size < 5000:
                url = f"https://artofproblemsolving.com/wiki/index.php/{year}_AIME_{contest}_Problems"
                print(f"Downloading {year} AIME {contest} problems...", end=" ", flush=True)
                html = fetch_page(url)
                if html:
                    prob_file.write_text(html)
                    print(f"OK ({len(html)} bytes)")
                else:
                    print("FAILED")
                time.sleep(1)
            else:
                print(f"Already cached: {prob_file.name}")

            # Download answer key
            ans_file = CACHE_DIR / f"{year}_AIME_{contest}_Answer_Key.html"
            if not ans_file.exists() or ans_file.stat().st_size < 1000:
                url = f"https://artofproblemsolving.com/wiki/index.php/{year}_AIME_{contest}_Answer_Key"
                print(f"Downloading {year} AIME {contest} answers...", end=" ", flush=True)
                html = fetch_page(url)
                if html:
                    ans_file.write_text(html)
                    print(f"OK ({len(html)} bytes)")
                else:
                    print("FAILED")
                time.sleep(1)
            else:
                print(f"Already cached: {ans_file.name}")


def extract_problems(html):
    """Extract problems from an AoPS AIME problems page."""
    problems = []

    # Try multiple split patterns
    sections = re.split(r'<h[23]>\s*<span class="mw-headline"[^>]*>\s*Problem\s+\d+\s*</span>\s*</h[23]>', html)
    if len(sections) <= 1:
        sections = re.split(r'<span class="mw-headline"[^>]*>\s*Problem\s+\d+\s*</span>', html)

    for i, section in enumerate(sections[1:], 1):
        # Cut at next heading
        section = re.split(r'<h[23]>', section)[0]

        # Extract alt text from images (LaTeX)
        section = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*?>', r' $\1$ ', section)
        section = re.sub(r'<img[^>]*?>', '', section)

        # Strip tags
        text = re.sub(r'<[^>]+>', ' ', section)
        text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        text = text.replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'\s*Solution\s*$', '', text)
        text = re.sub(r'\s*See also.*$', '', text, flags=re.DOTALL)

        if len(text) > 20:
            problems.append({"number": i, "text": text})

    return problems


def extract_answers(html):
    """Extract answers from an answer key page."""
    answers = {}
    ol_match = re.search(r'<ol[^>]*>(.*?)</ol>', html, re.DOTALL)
    if ol_match:
        lis = re.findall(r'<li[^>]*>(.*?)</li>', ol_match.group(1), re.DOTALL)
        for i, li in enumerate(lis):
            clean = re.sub(r'<[^>]+>', '', li).strip()
            if clean and re.match(r'^\d+$', clean):
                answers[i + 1] = clean

    if len(answers) == 15:
        return answers

    # Fallback: look for numbered answers in the content
    content = re.sub(r'<[^>]+>', ' ', html)
    pairs = re.findall(r'(\d{1,2})\s*[.:]\s*(\d{3})', content)
    for num_str, ans in pairs:
        num = int(num_str)
        if 1 <= num <= 15:
            answers[num] = ans

    return answers


def parse_all():
    """Phase 2: Parse all downloaded pages."""
    all_data = {}

    for year in YEARS:
        for contest in CONTESTS:
            key = f"aime_{contest.lower()}_{year}"
            prob_file = CACHE_DIR / f"{year}_AIME_{contest}_Problems.html"
            ans_file = CACHE_DIR / f"{year}_AIME_{contest}_Answer_Key.html"

            if not prob_file.exists():
                print(f"Missing: {prob_file.name}")
                continue

            html = prob_file.read_text()
            problems = extract_problems(html)

            answers = {}
            if ans_file.exists():
                answers = extract_answers(ans_file.read_text())

            # Fill in answers
            for p in problems:
                p['answer'] = answers.get(p['number'], None)

            all_data[key] = problems
            n_with_ans = sum(1 for p in problems if p.get('answer'))
            print(f"{key}: {len(problems)} problems, {n_with_ans} with answers")

    return all_data


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--parse-only', action='store_true')
    args = parser.parse_args()

    if not args.parse_only:
        download_all()

    if not args.download_only:
        all_data = parse_all()

        output_file = Path('/tmp/aime_aops_scraped.json')
        with open(output_file, 'w') as f:
            json.dump(all_data, f, indent=2)

        total = sum(len(v) for v in all_data.values())
        with_ans = sum(1 for v in all_data.values() for p in v if p.get('answer'))
        print(f"\nTotal: {total} problems, {with_ans} with answers")
        print(f"Saved to {output_file}")

        # Show sample
        for key, problems in list(all_data.items())[:2]:
            if problems:
                p = problems[0]
                print(f"\n{key} Problem {p['number']}:")
                print(f"  Text: {p['text'][:200]}...")
                print(f"  Answer: {p.get('answer', 'UNKNOWN')}")


if __name__ == '__main__':
    main()