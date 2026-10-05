"""真实浏览器端到端验证：打开页面 -> 注册登录 -> 网页上传 -> 等待 done -> 网页问答 -> 工具调用。

用法: BASE=http://localhost:8000 python scripts/browser_check.py
需要 playwright + chromium。
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.getenv("BASE", "http://localhost:8000")
SAMPLE = os.getenv("SAMPLE", "samples/Java并发编程.pdf")
SHOT_DIR = os.getenv("SHOT_DIR", "screenshots")


def main() -> int:
    os.makedirs(SHOT_DIR, exist_ok=True)
    username = f"ui_{int(time.time())}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: print("  [console]", m.type, m.text))
        page.on("pageerror", lambda e: print("  [pageerror]", e))

        print("1) 打开首页")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector("#auth-screen:not(.hidden)")
        page.screenshot(path=f"{SHOT_DIR}/01_login.png")
        print("   OK 登录页已渲染")

        print("2) 切换到注册并注册")
        page.click('.tab[data-tab="register"]')
        page.fill('#register-form input[name="username"]', username)
        page.fill('#register-form input[name="password"]', "ui123456")
        page.click('#register-form button[type="submit"]')
        page.wait_for_selector("#app-screen:not(.hidden)", timeout=15000)
        page.wait_for_selector("#health-badge.ok", timeout=10000)
        print(f"   OK 已进入主界面，用户={username}")

        print("3) 网页上传文档")
        page.set_input_files("#file-input", SAMPLE)
        page.wait_for_selector(".doc-item", timeout=15000)
        name = page.inner_text(".doc-name")
        print("   OK 文档已出现:", name)

        print("4) 等待处理完成 (status=done)")
        deadline = time.time() + 30
        status = ""
        while time.time() < deadline:
            status = page.inner_text(".doc-item .status")
            if status in ("已完成", "失败"):
                break
            time.sleep(0.5)
        assert status == "已完成", f"ingest 未完成，实际状态={status}"
        page.screenshot(path=f"{SHOT_DIR}/02_uploaded.png")
        print("   OK 状态:", status, "|", page.inner_text(".doc-item .doc-meta"))

        print("5) 网页提问（RAG + 引用）")
        page.fill("#chat-input", "volatile为什么不能保证i++线程安全？")
        page.click("#send-btn")
        page.wait_for_selector(".msg-row.assistant .bubble:not(.typing)", timeout=30000)
        page.wait_for_selector(".citation", timeout=15000)
        n_cit = page.locator(".citation").count()
        print(f"   OK 回答已返回，引用数={n_cit}")
        page.screenshot(path=f"{SHOT_DIR}/03_rag_answer.png", full_page=True)

        print("6) 网页提问（Agent 工具调用）")
        page.fill("#chat-input", "查询北京今天的天气，并结合我知识库中的跑步计划告诉我今天适不适合户外训练。")
        page.click("#send-btn")
        page.wait_for_selector(".tool-call", timeout=30000)
        tool_text = page.inner_text(".tool-call-head")
        print("   OK 工具调用已显示:", tool_text)
        page.screenshot(path=f"{SHOT_DIR}/04_tool_call.png", full_page=True)

        print("7) 刷新页面，确认登录态保持")
        page.reload(wait_until="networkidle")
        page.wait_for_selector("#app-screen:not(.hidden)", timeout=15000)
        assert page.locator(".doc-item").count() >= 1
        print("   OK 刷新后仍登录且文档还在")

        browser.close()

    print("\nBROWSER E2E OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
