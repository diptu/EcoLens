#!/usr/bin/env python3
"""Take screenshots of the running EcoLens landing page.

Scrolls the page first to trigger all `whileInView` animations, then
captures full-page + per-section screenshots at 2x retina.
"""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/preview")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

URL = "http://localhost:3000/"


async def trigger_all_animations(page) -> None:
    """Scroll through the page to trigger every whileInView animation."""
    # Get full page height
    height = await page.evaluate("document.body.scrollHeight")
    viewport_h = await page.evaluate("window.innerHeight")
    print(f"  page height={height}px, viewport={viewport_h}px")
    # Scroll in steps
    step = int(viewport_h * 0.6)
    pos = 0
    while pos < height:
        await page.evaluate(f"window.scrollTo(0, {pos})")
        await page.wait_for_timeout(450)
        pos += step
    # Scroll to bottom and back to top so final state is "in view"
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(800)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1500)


async def take_per_section_screenshots(page, prefix: str) -> None:
    """Capture each section at its natural scroll position."""
    sections = [
        ("hero", 0, 1000),
        ("stats", 900, 900),
        ("globe", 1500, 1100),
        ("features", 2400, 900),
        ("trusted", 3100, 700),
        ("cta", 3700, 900),
    ]
    for name, scroll_y, viewport_h in sections:
        # The mobile/full-page ones don't need this
        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
        await page.wait_for_timeout(900)
        path = OUTPUT_DIR / f"{prefix}-{name}.png"
        await page.set_viewport_size({"width": 1440, "height": viewport_h})
        await page.screenshot(path=str(path), full_page=False)
        print(f"  {name:9} -> {path}")


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            # ─────────────  Desktop (1440x900, 2x retina)  ─────────────
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            page.set_default_timeout(60_000)
            print(f"\n  loading {URL} ...")
            await page.goto(URL, wait_until="load", timeout=30_000)
            await page.wait_for_timeout(2500)

            # Full-page screenshot
            print("  capturing full page ...")
            await page.set_viewport_size({"width": 1440, "height": 900})
            full_path = OUTPUT_DIR / "ecolens-landing-full.png"
            await page.screenshot(path=str(full_path), full_page=True)
            print(f"  full page  -> {full_path}")

            # Above-the-fold
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)
            fold_path = OUTPUT_DIR / "ecolens-landing-fold.png"
            await page.screenshot(path=str(fold_path), full_page=False)
            print(f"  above fold -> {fold_path}")

            # Per-section
            print("  capturing per-section ...")
            await take_per_section_screenshots(page, "ecolens-landing")

            # ─────────────  Mobile (iPhone 14 Pro: 390x844, 2x retina)  ─────────────
            print("\n  mobile capture ...")
            m_ctx = await browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
            )
            m_page = await m_ctx.new_page()
            await m_page.goto(URL, wait_until="load", timeout=30_000)
            await m_page.wait_for_timeout(2000)
            m_path = OUTPUT_DIR / "ecolens-landing-mobile.png"
            await m_page.screenshot(path=str(m_path), full_page=True)
            print(f"  mobile     -> {m_path}")

            print(f"\n  All screenshots saved to: {OUTPUT_DIR}")
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
