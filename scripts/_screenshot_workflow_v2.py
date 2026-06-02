"""更稳定的截图脚本：先把 viewport 拉到全页高度，再截。"""
import asyncio
from pathlib import Path

OUT_DIR = Path("outputs/_phase1_screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await context.new_page()

        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        await page.wait_for_selector("text=AI 抽取", timeout=15000)
        btn = page.get_by_role("button", name="🤖 AI 抽取 / 重新抽取")
        await btn.click()
        print("clicked AI 抽取")
        await page.wait_for_selector("text=人物 IP 锁定", timeout=120000)
        await asyncio.sleep(8)

        # 拉高 viewport，截整个页面
        body_height = await page.evaluate("document.body.scrollHeight")
        print(f"body height = {body_height}")
        await page.set_viewport_size({"width": 1600, "height": min(body_height + 200, 8000)})
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUT_DIR / "10_full_tall.png"), full_page=False)
        print(f"saved 10_full_tall.png")

        # 滚到每个 step 截 viewport
        await page.set_viewport_size({"width": 1600, "height": 1000})
        for js_anchor, fname in [
            ("document.querySelectorAll('summary').forEach(s => { if (s.innerText.includes('Step 3：')) s.scrollIntoView({behavior:'auto', block:'center'}); })", "11_step3_centered.png"),
            ("document.querySelectorAll('summary').forEach(s => { if (s.innerText.includes('Step 4：')) s.scrollIntoView({behavior:'auto', block:'center'}); })", "12_step4_centered.png"),
            ("document.querySelectorAll('summary').forEach(s => { if (s.innerText.includes('Step 5：')) s.scrollIntoView({behavior:'auto', block:'center'}); })", "13_step5_centered.png"),
            ("document.querySelectorAll('summary').forEach(s => { if (s.innerText.includes('Step 6：')) s.scrollIntoView({behavior:'auto', block:'center'}); })", "14_step6_centered.png"),
            ("document.querySelectorAll('summary').forEach(s => { if (s.innerText.includes('Step 7：')) s.scrollIntoView({behavior:'auto', block:'center'}); })", "15_step7_centered.png"),
        ]:
            try:
                await page.evaluate(js_anchor)
                await asyncio.sleep(1)
                await page.screenshot(path=str(OUT_DIR / fname), full_page=False)
                print(f"saved {fname}")
            except Exception as e:
                print(f"截 {fname} 失败：{e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
