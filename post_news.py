"""Post the latest Elder Scrolls Online news to a Discord webhook.

- Reads the article list on the ESO news page (the <article class="tier-2-list-item"> blocks)
- Takes the 3 newest posts
- Skips anything already posted (tracked in posted.json)
- Posts oldest -> newest, each as an embed with image, date and tags
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

NEWS_URL = "https://www.elderscrollsonline.com/en-us/news"
MAX_POSTS = 3
STATE_FILE = Path("posted.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ESO-News-Webhook/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}
AGE_COOKIE = os.environ.get("ESO_AGE_COOKIE", "")
if AGE_COOKIE:
    HEADERS["Cookie"] = AGE_COOKIE


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        final_url = resp.geturl()
        body = resp.read().decode("utf-8", errors="replace")
    if "agegate" in final_url:
        sys.exit("Blocked by ESO's age gate. Check the ESO_AGE_COOKIE secret.")
    return body


def clean(text):
    """Strip tags, decode entities, collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def meta(page, prop):
    for pattern in (
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']',
    ):
        m = re.search(pattern, page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def parse_listing(listing_html):
    """Return the first MAX_POSTS posts from the news list, newest first."""
    blocks = re.findall(
        r'<article[^>]*class="[^"]*tier-2-list-item[^"]*"[^>]*>(.*?)</article>',
        listing_html,
        re.S,
    )
    posts = []
    for block in blocks:
        href = re.search(r'href="(/en-us/news/post/\d+)"', block)
        title = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        if not href or not title:
            continue
        image = re.search(r'<img[^>]+src="([^"]+)"', block)
        excerpt = re.search(r"<p>(.*?)</p>", block, re.S)  # plain <p>, not <p class="date">
        date = re.search(r'<p class="date">\s*([\d/]+)', block)
        tags = re.findall(r'<a[^>]+class="label[^"]*"[^>]*>(.*?)</a>', block, re.S)
        posts.append(
            {
                "url": urljoin(NEWS_URL, href.group(1)),
                "title": clean(title.group(1)),
                "image": image.group(1) if image else "",
                "excerpt": clean(excerpt.group(1)) if excerpt else "",
                "date": date.group(1) if date else "",
                "tags": [clean(t) for t in tags],
            }
        )
        if len(posts) == MAX_POSTS:
            break
    return posts


def load_state():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def iso_date(us_date):
    """10/21/2026 -> 2026-10-21T00:00:00Z (Discord shows it as the embed time)."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", us_date)
    if not m:
        return None
    month, day, year = m.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}T00:00:00Z"


def full_description(post):
    """The list cuts the excerpt off with '…', so try the article's own summary."""
    try:
        desc = meta(fetch(post["url"]), "og:description")
        if desc:
            return desc
    except Exception as exc:  # fall back to the list excerpt
        print("Could not fetch article summary:", exc)
    return post["excerpt"]


def post_to_discord(webhook, post):
    footer = "The Elder Scrolls Online"
    if post["tags"]:
        footer += " • " + ", ".join(post["tags"])
    embed = {
        "title": post["title"][:256],
        "url": post["url"],
        "description": full_description(post)[:500],
        "color": 0xC9A227,
        "footer": {"text": footer},
    }
    if post["image"]:
        embed["image"] = {"url": post["image"]}
    ts = iso_date(post["date"])
    if ts:
        embed["timestamp"] = ts

    data = json.dumps({"username": "ESO News", "embeds": [embed]}).encode()
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": HEADERS["User-Agent"]},
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    webhook = os.environ["DISCORD_WEBHOOK_URL"]
    posts = parse_listing(fetch(NEWS_URL))
    if not posts:
        sys.exit("No posts found in the news list. The page layout may have changed.")

    seen = load_state()
    new_posts = [p for p in posts if p["url"] not in seen]
    print(f"Found {len(posts)} posts, {len(new_posts)} new")

    for post in reversed(new_posts):  # oldest first
        post_to_discord(webhook, post)
        seen.add(post["url"])
        print("Posted", post["url"])
        time.sleep(1)  # stay well under Discord's rate limit

    STATE_FILE.write_text(json.dumps(sorted(seen), indent=2))


if __name__ == "__main__":
    main()
