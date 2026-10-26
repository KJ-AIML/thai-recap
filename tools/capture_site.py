"""Capture full-page + per-viewport screenshots and a smooth scrolling video of a public site (desktop & mobile)."""
import sys, asyncio, os
from playwright.async_api import async_playwright
URL = sys.argv[1]; OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)
CHROME = "/usr/bin/google-chrome"

async def shoot(p, name, vw, vh, mobile, url):
    b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    ctx = await b.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=2 if mobile else 1,
                              is_mobile=mobile, has_touch=mobile, record_video_dir=f"{OUT}/vid_{name}",
                              record_video_size={"width": vw, "height": vh})
    pg = await ctx.new_page()
    await pg.goto(url, wait_until="networkidle", timeout=60000)
    await pg.wait_for_timeout(2500)
    H = await pg.evaluate("document.documentElement.scrollHeight")
    # slow scroll (also triggers lazy/scroll animations), viewport shots along the way
    y, k = 0, 0
    while y < H:
        await pg.screenshot(path=f"{OUT}/{name}_vp{k:02d}.png")
        for _ in range(30):
            y += vh * 0.8 / 30
            await pg.evaluate(f"window.scrollTo(0,{y})"); await pg.wait_for_timeout(33)
        await pg.wait_for_timeout(700); k += 1
        H = await pg.evaluate("document.documentElement.scrollHeight")
    await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(800)
    await pg.screenshot(path=f"{OUT}/{name}_full.png", full_page=True)
    await ctx.close(); await b.close()
    print(name, "height", H, "viewport shots", k)

async def main():
    async with async_playwright() as p:
        await shoot(p, "desk_en", 1440, 900, False, URL)
        await shoot(p, "mob_en", 390, 844, True, URL)
        await shoot(p, "desk_th", 1440, 900, False, URL.rstrip("/") + "/th/")
        await shoot(p, "mob_th", 390, 844, True, URL.rstrip("/") + "/th/")
asyncio.run(main())
