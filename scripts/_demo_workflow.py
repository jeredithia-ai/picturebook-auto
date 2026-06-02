"""Phase 1 完整演示：模拟点击每步 ✅ 确认，截图每步解锁后状态。"""
import asyncio
from pathlib import Path

OUT_DIR = Path("outputs/_phase1_screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def click_confirm(page, step_num: int) -> bool:
    """点击 ✓ 确认 Step X 按钮。"""
    try:
        btn = page.get_by_test_id(f"stBaseButton-primary").filter(
            has_text=f"确认 Step {step_num}"
        ).first
        await btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)
        await btn.click()
        print(f"  ✓ clicked confirm for step {step_num}")
        return True
    except Exception as e:
        # 备用：找包含"确认 Step"和 step_num 的任何按钮
        try:
            btn = page.locator(f"button:has-text('确认 Step {step_num}')").first
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.3)
            await btn.click()
            print(f"  ✓ clicked confirm for step {step_num} (fallback)")
            return True
        except Exception as e2:
            # 再退一步：找包含"Step X"和"进入"的按钮
            try:
                # ✅ 确认人物 IP，进入风格设定 / ✅ 确认风格设定，进入分页编辑
                step_label_map = {
                    2: "确认人物 IP",
                    3: "确认风格设定",
                    4: "确认分页事件",
                    5: "提示词 OK",
                    6: "图都满意",
                }
                if step_num in step_label_map:
                    btn = page.locator(f"button:has-text('{step_label_map[step_num]}')").first
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await btn.click()
                    print(f"  ✓ clicked confirm for step {step_num} (label fallback)")
                    return True
            except Exception as e3:
                pass
            print(f"  ✗ step {step_num} confirm not found: {e2}")
            return False


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1100})
        page = await context.new_page()
        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        await page.wait_for_selector("text=AI 抽取", timeout=15000)

        # === Screenshot 1：初始（Step 1 active, Step 2-7 locked）===
        await page.screenshot(path=str(OUT_DIR / "demo_01_initial.png"), full_page=False)
        print("saved demo_01_initial.png")

        # === 点 AI 抽取 ===
        await page.get_by_role("button", name="🤖 AI 抽取 / 重新抽取").click()
        await page.wait_for_selector("text=人物 IP 锁定", timeout=120000)
        await asyncio.sleep(5)

        # 滚到进度条位置（找绘本组装工作流标题）
        try:
            await page.locator("text=绘本组装工作流").first.scroll_into_view_if_needed()
            await asyncio.sleep(1)
        except Exception:
            pass

        # === Screenshot 2：抽取后（Step 1 done, Step 2 active）===
        await page.screenshot(path=str(OUT_DIR / "demo_02_step2_active.png"), full_page=False)
        print("saved demo_02_step2_active.png")

        # === 点 Step 2 ✓ 确认 ===
        ok = await click_confirm(page, 2)
        if ok:
            await asyncio.sleep(4)  # 等 rerun
            try:
                await page.locator("text=绘本组装工作流").first.scroll_into_view_if_needed()
                await asyncio.sleep(1)
            except Exception:
                pass
            await page.screenshot(path=str(OUT_DIR / "demo_03_step3_active.png"), full_page=False)
            print("saved demo_03_step3_active.png")

        # 滚到 Step 3 看风格设定面板
        try:
            await page.locator("text=风格背景设定（全局应用").first.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await page.screenshot(path=str(OUT_DIR / "demo_04_style_panel.png"), full_page=False)
            print("saved demo_04_style_panel.png")
        except Exception as e:
            print(f"找风格设定失败：{e}")

        # === 点 Step 3 ✓ 确认 ===
        ok = await click_confirm(page, 3)
        if ok:
            await asyncio.sleep(4)
            try:
                await page.locator("text=分页事件编辑").first.scroll_into_view_if_needed()
                await asyncio.sleep(1)
                await page.screenshot(path=str(OUT_DIR / "demo_05_step4_active.png"), full_page=False)
                print("saved demo_05_step4_active.png")
            except Exception:
                pass

        # === 点 Step 4 ✓ 确认 ===
        ok = await click_confirm(page, 4)
        if ok:
            await asyncio.sleep(4)
            try:
                await page.locator("text=提示词预览与微调").first.scroll_into_view_if_needed()
                await asyncio.sleep(1)
                await page.screenshot(path=str(OUT_DIR / "demo_06_step5_active.png"), full_page=False)
                print("saved demo_06_step5_active.png")
            except Exception:
                pass

        # 滚到进度条看 4 步完成
        try:
            await page.locator("text=绘本组装工作流").first.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await page.screenshot(path=str(OUT_DIR / "demo_07_progress_after_4_confirms.png"), full_page=False)
            print("saved demo_07_progress_after_4_confirms.png")
        except Exception:
            pass

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
