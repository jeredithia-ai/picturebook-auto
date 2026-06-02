"""V3：放大 viewport 到 4000 高一次截全。"""
import asyncio
from pathlib import Path

OUT_DIR = Path("outputs/_phase1_screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 直接用很大的 viewport
        context = await browser.new_context(viewport={"width": 1600, "height": 4000})
        page = await context.new_page()

        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        await page.wait_for_selector("text=AI 抽取", timeout=15000)
        await page.get_by_role("button", name="🤖 AI 抽取 / 重新抽取").click()
        print("clicked AI 抽取")
        await page.wait_for_selector("text=人物 IP 锁定", timeout=120000)
        await asyncio.sleep(8)

        # 用真正可滚动的元素（streamlit main）
        await page.evaluate("""
          const main = document.querySelector('section.main') || document.querySelector('[data-testid="stAppViewContainer"]');
          if (main) main.scrollTop = 0;
          window.scrollTo(0, 0);
        """)
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUT_DIR / "20_top.png"), full_page=False)
        print("saved 20_top.png (viewport=4000)")

        # 滚到中间 (要把 stMain 容器整个滚)
        await page.evaluate("""
          const main = document.querySelector('section.main') || document.querySelector('[data-testid="stAppViewContainer"]') || document.scrollingElement;
          if (main) main.scrollTop = 1500;
        """)
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUT_DIR / "21_mid.png"), full_page=False)
        print("saved 21_mid.png")

        # 滚到底
        await page.evaluate("""
          const main = document.querySelector('section.main') || document.querySelector('[data-testid="stAppViewContainer"]') || document.scrollingElement;
          if (main) main.scrollTop = main.scrollHeight;
        """)
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUT_DIR / "22_bottom.png"), full_page=False)
        print("saved 22_bottom.png")

        # 真正 full_page
        await page.screenshot(path=str(OUT_DIR / "23_fullpage.png"), full_page=True)
        print("saved 23_fullpage.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
