"""V4: viewport=8000, just for capturing full-page state."""
import asyncio
from pathlib import Path

OUT_DIR = Path("outputs/_phase1_screenshots")


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 9000})
        page = await context.new_page()
        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        await page.wait_for_selector("text=AI 抽取", timeout=15000)
        await page.get_by_role("button", name="🤖 AI 抽取 / 重新抽取").click()
        await page.wait_for_selector("text=人物 IP 锁定", timeout=120000)
        await asyncio.sleep(8)

        # 先收起 Step 2，让 Step 3-7 都能在一屏看到
        await page.evaluate("""
          document.querySelectorAll('[data-testid="stExpander"] details[open]').forEach(d => {
            if (d.innerText.includes('Step 2')) d.removeAttribute('open');
          });
        """)
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUT_DIR / "30_step2_collapsed.png"), full_page=True)
        print("saved 30_step2_collapsed.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
