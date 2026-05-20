"""
Uses Playwright headless browser to intercept .m3u8 stream URLs
from Gjirafa Slow TV camera pages.

Run: python extract_streams.py
"""
import asyncio
import re
from playwright.async_api import async_playwright

CAMERAS = {
    "pejton":    "https://video.gjirafa.com/slow-tv-pejton",
    "veternik":  "https://video.gjirafa.com/slow-tv-veternik-2",
    "tokbashqe": "https://video.gjirafa.com/slow-tv-tokbashqe",
}

async def extract(page, cam_id, url):
    found = []

    def on_request(request):
        req_url = request.url
        if ".m3u8" in req_url or "vpplayer" in req_url or "live" in req_url.lower():
            found.append(req_url)

    page.on("request", on_request)

    print(f"\n[{cam_id}] Loading {url} ...")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"  Navigation error: {e}")

    # Click play button if present
    try:
        play_btn = page.locator("button[aria-label*='play' i], .vjs-play-control, [class*='play']").first
        await play_btn.click(timeout=3000)
    except Exception:
        pass

    # Wait for network activity
    await asyncio.sleep(8)

    unique = list(dict.fromkeys(found))
    if unique:
        print(f"  Found {len(unique)} URLs:")
        for u in unique:
            print(f"    {u}")
    else:
        print("  No stream URLs captured.")
        # Dump all captured requests for debugging
        print("  All captured network requests:")
        for u in found[:20]:
            print(f"    {u}")

    return unique

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124"
        )

        results = {}
        for cam_id, url in CAMERAS.items():
            page = await context.new_page()
            urls = await extract(page, cam_id, url)
            results[cam_id] = urls
            await page.close()

        await browser.close()

    print("\n\n===== RESULTS (paste into config.py) =====")
    for cam_id, urls in results.items():
        m3u8 = [u for u in urls if ".m3u8" in u]
        best = m3u8[0] if m3u8 else (urls[0] if urls else "NOT FOUND")
        print(f'  "{cam_id}": "{best}"')

asyncio.run(main())
