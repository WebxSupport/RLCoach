"""Screenshot utility for the RLCoach visual loop (dev only).

Usage:
  python devtools/shoot.py --url http://localhost:8801/ --out shots/landing.png
  python devtools/shoot.py --url http://localhost:8801/ --out shots/landing-m.png --width 390
  python devtools/shoot.py --url ... --cookie devseed-session --js "switchTab('stats')" --wait 800

Options:
  --width N        viewport width (default 1280; 390 = mobile)
  --height N       viewport height (default 800)
  --full           full-page screenshot
  --cookie SID     set session_id cookie before load (DEV_SEED session)
  --js CODE        evaluate JS after load (e.g. switch tab)
  --click SEL      click a selector after load (repeatable)
  --fill SEL=VAL   fill an input (repeatable)
  --wait MS        extra settle time after actions (default 600)
  --reduced-motion emulate prefers-reduced-motion
"""
import argparse
import pathlib
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--cookie", default=None)
    ap.add_argument("--js", default=None)
    ap.add_argument("--click", action="append", default=[])
    ap.add_argument("--fill", action="append", default=[])
    ap.add_argument("--wait", type=int, default=600)
    ap.add_argument("--reduced-motion", action="store_true")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            reduced_motion="reduce" if args.reduced_motion else "no-preference",
            device_scale_factor=2,
        )
        if args.cookie:
            u = urlparse(args.url)
            ctx.add_cookies([{
                "name": "session_id", "value": args.cookie,
                "domain": u.hostname, "path": "/",
            }])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(args.url, wait_until="networkidle", timeout=30000)
        for f in args.fill:
            sel, _, val = f.partition("=")
            page.fill(sel, val)
        for sel in args.click:
            page.click(sel)
        if args.js:
            page.evaluate(args.js)
        page.wait_for_timeout(args.wait)
        page.screenshot(path=str(out), full_page=args.full)
        browser.close()

    print(f"saved {out}")
    if errors:
        print("PAGE ERRORS:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
