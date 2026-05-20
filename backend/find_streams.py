"""
Helper script to extract stream URLs from Gjirafa camera pages.
Run: python find_streams.py
"""
import re
import sys
import urllib.request
import json

CAMERAS = {
    "pejton":    "https://video.gjirafa.com/slow-tv-pejton",
    "veternik":  "https://video.gjirafa.com/slow-tv-veternik-2",
    "tokbashqe": "https://video.gjirafa.com/slow-tv-tokbashqe",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", errors="replace")

PATTERNS = [
    ("m3u8 direct",      r"https://[^\s\"']+\.m3u8"),
    ("videoId",          r'"videoId"\s*:\s*"([^"]+)"'),
    ("video_id",         r'"video_id"\s*:\s*"([^"]+)"'),
    ("liveId",           r'"liveId"\s*:\s*"([^"]+)"'),
    ("projectId",        r'"projectId"\s*:\s*"([^"]+)"'),
    ("vpplayer domain",  r"https://[^\s\"']*vpplayer\.tech[^\s\"']*"),
    ("cdn domain",       r"https://cdn\.vpplayer\.tech/[^\s\"']+"),
    ("embed src",        r'src="(https://video\.gjirafa\.com/embed/[^"]+)"'),
    ("data-video",       r'data-video(?:id)?="([^"]+)"'),
    ("data-live",        r'data-live(?:id)?="([^"]+)"'),
]

for cam_id, url in CAMERAS.items():
    print(f"\n{'='*60}")
    print(f"Camera: {cam_id}  ->  {url}")
    print('='*60)
    try:
        html = fetch(url)
        found_any = False
        for label, pat in PATTERNS:
            hits = re.findall(pat, html)
            if hits:
                unique = list(dict.fromkeys(hits))[:4]
                print(f"  [{label}]")
                for h in unique:
                    print(f"    {h}")
                found_any = True
        if not found_any:
            print("  (no patterns matched — page may be fully JS-rendered)")
            # Print a snippet for manual inspection
            snippet_start = html.find("gjirafa")
            if snippet_start > 0:
                print("  Snippet:", html[snippet_start:snippet_start+300])
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone.")
