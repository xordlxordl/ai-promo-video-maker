"""Directly open URL to take 4K screenshots (Playwright, no AI browser extension required).

python3 scripts/shot.py <url> <name>                          # 1920x1080 @2x -> out/shots/<name>-0.jpg (3840x2160)
python3 scripts/shot.py <url> <name> --scroll 0 1400 2800      # Scroll main container to each offset and take a screenshot
python3 scripts/shot.py <url> <name> --tall 4200 --scale 1.25  # Increase viewport height for full-page tall screenshot (captures sites with internal scroll)
python3 scripts/shot.py <url> <name> --hide ".banner" ".float-bar" --eval "document.title = ''"
python3 scripts/shot.py --login <url>                          # For sites requiring login: run this first
python3 <tool_dir>/template/scripts/shot.py file:///<abs_path>/A.html A --out "<output_dir>/<project>/sample_frames"   # Capture code-rendered style samples before project creation

--login opens a browser window with GUI for user to log in; close the window when done.
Login session is saved to out/.browser-profile/, used by subsequent screenshots in this project (contains cookies, do not share).
Hides top-right account avatar by default (images within top 80px and right 240px); use --keep-avatar to keep.
Requires Playwright: pip install playwright && playwright install chromium
"""
import argparse
import os

from playwright.sync_api import TimeoutError as PwTimeout
from playwright.sync_api import sync_playwright

from snapshot import AVATAR, SCROLL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, "out", ".browser-profile")

LAZY = """async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const els = [document.scrollingElement, ...document.querySelectorAll('*')].filter(e => e && (e === document.scrollingElement ||
    (e.scrollHeight > e.clientHeight + 200 && /(auto|scroll)/.test(getComputedStyle(e).overflowY || ''))));
  for (const s of els.slice(0, 8)) {
    for (let y = 0; y < Math.min(s.scrollHeight, 20000); y += 700) { s.scrollTop = y; await sleep(100); }
    s.scrollTop = 0;
  }
  window.scrollTo(0, 0);
}"""


def open_page(ctx, url, wait):
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.goto(url, wait_until="load", timeout=90000)
    try:
        pg.wait_for_load_state("networkidle", timeout=15000)
    except PwTimeout:
        pass
    pg.wait_for_timeout(int(wait * 1000))
    return pg


def login(url):
    os.makedirs(PROFILE, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, headless=False, viewport=None)
        pg = open_page(ctx, url, 0)
        print("Browser window opened: please log in inside it, then close the window when done.")
        pg.wait_for_event("close", timeout=0)
        ctx.close()
    print(f"Login session saved to {PROFILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--login", action="store_true", help="Open a browser with GUI for user login")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--scale", type=float, default=2)
    ap.add_argument("--scroll", type=int, nargs="*", default=[0])
    ap.add_argument("--tall", type=int, help="Viewport height in CSS pixels for full-page tall screenshot")
    ap.add_argument("--hide", nargs="*", default=[], help="CSS selectors to hide before screenshot (banners, floating bars, popups)")
    ap.add_argument("--eval", dest="js", help="JS to execute in page before screenshot (for page cleanup)")
    ap.add_argument("--wait", type=float, default=1.5, help="Seconds to wait after page load")
    ap.add_argument("--keep-avatar", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "shots"))
    a = ap.parse_args()

    if a.login:
        return login(a.url)
    if not a.name:
        ap.error("Missing <name>")
    os.makedirs(a.out, exist_ok=True)
    view = {"viewport": {"width": a.width, "height": a.tall or a.height}, "device_scale_factor": a.scale}
    with sync_playwright() as p:
        if os.path.isdir(PROFILE):
            ctx = p.chromium.launch_persistent_context(PROFILE, headless=True, **view)
        else:
            ctx = p.chromium.launch().new_context(**view)
        pg = open_page(ctx, a.url, a.wait)
        pg.evaluate(LAZY)
        pg.wait_for_timeout(800)
        if not a.keep_avatar:
            pg.evaluate(AVATAR)
        for sel in a.hide:
            pg.add_style_tag(content=f"{sel} {{ display: none !important; }}")
        if a.js:
            pg.evaluate(f"() => {{ {a.js} }}")
        for i, y in enumerate([0] if a.tall else a.scroll):
            pg.evaluate(SCROLL, y)
            pg.wait_for_timeout(900)
            path = os.path.join(a.out, f"{a.name}-{'tall' if a.tall else i}.jpg")
            pg.screenshot(path=path, type="jpeg", quality=90)
            print(path, pg.title()[:40])
        ctx.close()


if __name__ == "__main__":
    main()
