"""
IOM Exam Routine Watcher

Checks https://iom.edu.np/examination/exam-routine/ and sends a free push
notification (ntfy.sh) when a NEW exam routine appears. Routines only: no
results, no notices, no filtering by program or year.

Design notes:
- Entries are tracked by Google Drive file ID (not by title), so an amended
  or postponed routine with a new Drive link still triggers an alert.
- Any unseen file ID alerts, regardless of its date.
- First run initializes state silently (no alerts for existing routines).
- State is never overwritten when the fetch fails or parses zero entries.
- If the notification fails, state is NOT updated, so the next run retries.

Usage:
    python check_routines.py            # normal run
    python check_routines.py --dry-run  # print parsed entries, change nothing
"""

import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

URL = "https://iom.edu.np/examination/exam-routine/"
STATE_FILE = "state.json"
MAX_SEEN = 200      # how many routine IDs to remember
MAX_LISTED = 10     # max routines listed in one notification

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL", "").strip()  # optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(r"[A-Z][a-z]{2} \d{1,2}, \d{4}")   # e.g. "Oct 08, 2026"
FILE_ID_RE = re.compile(r"/d/([A-Za-z0-9_-]+)")


# ---------------------------------------------------------------------
# Optional healthchecks.io ping (dead-man's switch)
# ---------------------------------------------------------------------
def ping(suffix=""):
    if not HEALTHCHECK_URL:
        return
    try:
        requests.get(HEALTHCHECK_URL.rstrip("/") + suffix, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"Healthcheck ping failed: {e}")


# ---------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------
def fetch_page(attempts=3):
    for i in range(1, attempts + 1):
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            print(f"Fetch attempt {i}/{attempts} failed: {e}")
            if i < attempts:
                time.sleep(5 * i)
    return None


def parse_routines(html):
    """Return a list of {id, title, date, url}, newest first (page order)."""
    soup = BeautifulSoup(html, "html.parser")
    items, seen_ids = [], set()

    for heading in soup.find_all(["h2", "h3"]):
        link = heading.find("a", href=True)
        if not link or "drive.google.com" not in link["href"]:
            continue

        url = link["href"].strip()
        m = FILE_ID_RE.search(url)
        key = m.group(1) if m else url
        if key in seen_ids:
            continue
        seen_ids.add(key)

        title = " ".join(link.get_text(" ", strip=True).split())

        date = ""
        date_node = heading.find_next(string=DATE_RE)
        if date_node:
            dm = DATE_RE.search(date_node)
            date = dm.group(0) if dm else ""

        items.append({"id": key, "title": title, "date": date, "url": url})

    return items


# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"initialized": False, "seen": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def to_state_entry(item):
    return {"id": item["id"], "title": item["title"], "date": item["date"]}


# ---------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------
def notify(new_items):
    """Send one ntfy notification. Returns True on success."""
    blocks = []
    for it in new_items[:MAX_LISTED]:
        lines = [it["title"]]
        if it["date"]:
            lines.append(it["date"])
        lines.append(it["url"])
        blocks.append("\n".join(lines))
    if len(new_items) > MAX_LISTED:
        blocks.append(f"...and {len(new_items) - MAX_LISTED} more: {URL}")

    n = len(new_items)
    # NOTE: HTTP header values must be latin-1 safe, so no emoji in Title.
    title = "New IOM Exam Routine" if n == 1 else f"{n} New IOM Exam Routines"
    click = new_items[0]["url"] if n == 1 else URL

    try:
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data="\n\n".join(blocks).encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "calendar",
                "Click": click,
            },
            timeout=15,
        )
        resp.raise_for_status()
        print(f"Notification sent ({n} routine(s)).")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Failed to send notification: {e}")
        return False


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main():
    dry_run = "--dry-run" in sys.argv

    html = fetch_page()
    if html is None:
        print("Site unreachable this run. Skipping; will retry next run.")
        return 0

    items = parse_routines(html)
    if not items:
        print("WARNING: parsed 0 routines. Site structure may have changed. "
              "State left untouched.")
        ping("/fail")
        return 0

    print(f"Parsed {len(items)} routine(s) from the page.")

    if dry_run:
        for it in items:
            print(f" - [{it['date']}] {it['title']} ({it['id']})")
        return 0

    state = load_state()

    # First run: remember what's there, alert on nothing.
    if not state.get("initialized"):
        state = {
            "initialized": True,
            "seen": [to_state_entry(it) for it in items][:MAX_SEEN],
        }
        save_state(state)
        print("First run: state initialized, no notification sent.")
        ping()
        return 0

    known = {e["id"] for e in state.get("seen", [])}
    new_items = [it for it in items if it["id"] not in known]

    if not new_items:
        print("No new routines.")
        ping()
        return 0

    print(f"Found {len(new_items)} new routine(s):")
    for it in new_items:
        print(f" - {it['title']}")

    if not NTFY_TOPIC:
        print("ERROR: NTFY_TOPIC is not set; cannot notify. State not updated.")
        ping("/fail")
        return 1

    if not notify(new_items):
        # Don't record these as seen, so the next run retries the alert.
        ping("/fail")
        return 1

    state["seen"] = ([to_state_entry(it) for it in new_items]
                     + state.get("seen", []))[:MAX_SEEN]
    save_state(state)
    ping()
    return 0


if __name__ == "__main__":
    sys.exit(main())
