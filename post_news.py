"""Post the latest Elder Scrolls Online news to a Discord webhook.

- Pulls the 3 newest posts from the ESO news page
- Skips anything already posted (tracked in posted.json)
- Posts oldest -> newest, each as an embed with its image
"""
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

NEWS_URL = "https://www.elderscrollsonline.com/en-us/news"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
# Optional: cookie string that gets past ESO's age gate (see README steps)
AGE_COOKIE = os.environ.get("ESO_AGE_COOKIE", "")
MAX_POSTS = 3
STATE_FILE = Path("posted.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ESO-News-Webhook/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}
if AGE_COOKIE:
    HEADERS["Cookie"] = AGE_COOKIE


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        final_url = resp.geturl()
        body = resp.read().decode("utf-8", errors="replace")
    if "agegate" in final_url:
        sys.exit(
            "Blocked by ESO's age gate. Set the ESO_AGE_COOKIE secret "
            "(see the setup steps)."
        )
    return body


def meta(page, prop):
    """Read an og:/twitter: meta tag, whichever attribute order is used."""
    for pattern in (
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']',
    ):
        m = re.search(pattern, page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def latest_article_links(listing_html):
    """Article links look like /en-us/news/<slug>; keep first-seen order."""
    links = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', listing_html):
        path = href.split("#")[0].split("?")[0].rstrip("/")
        if re.search(r"/en-us/news/[^/]+", path):
            full = urljoin(NEWS_URL, path)
            if full not in links:
                links.append(full)
    return links[:MAX_POSTS]


def load_state():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def post_to_discord(url, page):
    title = meta(page, "og:title") or url
    embed = {
        "title": title[:256],
        "url": url,
        "description": meta(page, "og:description")[:400],
        "color": 0xC9A227,
        "footer": {"text": "The Elder Scrolls Online"},
    }
    image = meta(page, "og:image")
    if image:
        embed["image"] = {"url": urljoin(url, image)}

    data = json.dumps({"username": "ESO News", "embeds": [embed]}).encode()
    req = urllib.request.Request(
        WEBHOOK,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": HEADERS["User-Agent"]},
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    listing = fetch(NEWS_URL)
    links = latest_article_links(listing)
    if not links:
        sys.exit("No article links found. The page may be JavaScript-rendered.")

    seen = load_state()
    new_links = [u for u in links if u not in seen]
    print(f"Found {len(links)} posts, {len(new_links)} new")

    for url in reversed(new_links):  # oldest first
        post_to_discord(url, fetch(url))
        seen.add(url)
        print("Posted", url)

    STATE_FILE.write_text(json.dumps(sorted(seen), indent=2))


if __name__ == "__main__":
    main()
