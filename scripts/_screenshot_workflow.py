"""Phase 1 验收：用 playwright 截图新 7 步绘本组装流程。

步骤：
1. 打开 http://localhost:8501
2. 等待 Streamlit 加载
3. 截首屏（输入表单 + 状态栏全锁）
4. 点 AI 抽取 → 等抽取完成
5. 截图：解锁到 Step 2 的状态
6. 滚动到底部截 Step 2-7 全状态
"""
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

        # 1. 首屏（未抽取）
        await page.screenshot(path=str(OUT_DIR / "01_initial.png"), full_page=True)
        print(f"saved 01_initial.png")

        # 等表单加载
        await page.wait_for_selector("text=AI 抽取", timeout=15000)
        # 找 AI 抽取按钮（form submit）
        btn = page.get_by_role("button", name="🤖 AI 抽取 / 重新抽取")
        await btn.click()
        print("clicked AI 抽取，等待...")

        # 等抽取完成（会出现 Step 2 expander）
        try:
            await page.wait_for_selector("text=人物 IP 锁定", timeout=120000)
            await asyncio.sleep(5)  # 等 rerender 稳
        except Exception as e:
            print(f"等抽取超时：{e}")

        # 2. 抽取后首屏（进度条 + Step 2 active）
        await page.screenshot(path=str(OUT_DIR / "02_after_extract.png"), full_page=True)
        print(f"saved 02_after_extract.png")

        # 滚到进度条位置
        try:
            elem = page.get_by_text("Step 1", exact=False).first
            await elem.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await page.screenshot(path=str(OUT_DIR / "03_progress_bar.png"), full_page=False)
            print(f"saved 03_progress_bar.png")
        except Exception as e:
            print(f"找 Step 1 位置失败：{e}")

        # 滚到 Step 3/4/5/6/7
        for label, fname in [
            ("风格背景设定", "04_step3_locked.png"),
            ("分页事件编辑", "05_step4_locked.png"),
            ("提示词预览", "06_step5_locked.png"),
            ("单页生图", "07_step6_locked.png"),
            ("组装 4 件套", "08_step7_locked.png"),
        ]:
            try:
                target = page.get_by_text(label, exact=False).first
                await target.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                await page.screenshot(path=str(OUT_DIR / fname), full_page=False)
                print(f"saved {fname}")
            except Exception as e:
                print(f"找 {label} 失败：{e}")

        # 最后再来一张全长图
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUT_DIR / "09_full_after_extract.png"), full_page=True)
        print(f"saved 09_full_after_extract.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
