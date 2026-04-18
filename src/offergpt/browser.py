from dataclasses import dataclass
from pathlib import Path
import platform
import subprocess
from time import sleep
from typing import Literal


CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_BROWSER_PROFILE = Path.home() / ".offergpt" / "browser-profile"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
PERSISTENT_TYPE_DELAY_MS = 25
BrowserMode = Literal["persistent", "cdp"]


@dataclass
class BrowserSession:
    context: object
    close_browser: bool = True
    browser: object | None = None

    def close(self) -> None:
        if self.close_browser:
            self.context.close()


def submit_to_chatgpt(
    prompt: str,
    profile_dir: Path = DEFAULT_BROWSER_PROFILE,
    browser_mode: BrowserMode = "cdp",
    cdp_url: str = DEFAULT_CDP_URL,
    new_tab: bool = False,
) -> None:
    if not prompt.strip():
        print("Skipping ChatGPT submission because the transcript is empty.")
        return

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        session = open_browser_session(playwright, profile_dir, browser_mode, cdp_url)

        try:
            page = open_chatgpt_page(session.context, browser_mode, new_tab)

            try:
                prompt_box = find_prompt_box(page, timeout=prompt_box_timeout(browser_mode))
            except PlaywrightTimeoutError:
                print("Could not find the ChatGPT prompt box yet.")
                print("If ChatGPT is asking you to log in, finish logging in inside the browser.")
                input("Press ENTER here after ChatGPT is open and ready for a prompt.")
                page.goto(CHATGPT_URL, wait_until="domcontentloaded")
                prompt_box = find_prompt_box(page, timeout=60_000)

            type_and_submit(prompt_box, prompt, browser_mode)
            print("Submitted transcript to ChatGPT.")
            if browser_mode == "cdp":
                activate_chrome()
            if session.close_browser:
                input("Browser is open. Press ENTER here when you are ready to close it.")
        except PlaywrightTimeoutError as exc:
            print("Could not find the ChatGPT prompt box.")
            print("If this is the first run, log in to ChatGPT in the opened browser, then run again.")
            raise SystemExit(1) from exc
        finally:
            session.close()


def open_browser_session(
    playwright,
    profile_dir: Path,
    browser_mode: BrowserMode,
    cdp_url: str,
) -> BrowserSession:
    if browser_mode == "cdp":
        return connect_to_cdp_browser(playwright, cdp_url)
    return launch_persistent_browser(playwright, profile_dir)


def launch_persistent_browser(playwright, profile_dir: Path) -> BrowserSession:
    launch_options = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "no_viewport": True,
        "args": [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],
    }

    try:
        print("Opening ChatGPT with installed Google Chrome...")
        context = playwright.chromium.launch_persistent_context(
            channel="chrome",
            **launch_options,
        )
    except Exception as exc:
        print(f"Could not launch installed Chrome: {exc}")
        print("Falling back to Playwright Chromium...")
        context = playwright.chromium.launch_persistent_context(**launch_options)

    return BrowserSession(context=context, close_browser=True)


def connect_to_cdp_browser(playwright, cdp_url: str) -> BrowserSession:
    print(f"Connecting to Chrome over CDP at {cdp_url}...")
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:
        print(f"Could not connect to Chrome over CDP: {exc}")
        print()
        print("Launch an automation-friendly Chrome first with:")
        print("  open -na 'Google Chrome' --args \\")
        print("    --remote-debugging-port=9222 \\")
        print("    --user-data-dir=$HOME/.offergpt/cdp-browser-profile")
        raise SystemExit(1) from exc

    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context(no_viewport=True)

    # Leave the CDP browser running so you can stay logged in between tests.
    return BrowserSession(context=context, close_browser=False, browser=browser)


def open_chatgpt_page(context, browser_mode: BrowserMode, new_tab: bool):
    if not new_tab:
        for page in context.pages:
            if page.url.startswith(CHATGPT_URL):
                print("Reusing existing ChatGPT tab.")
                page.bring_to_front()
                if browser_mode == "cdp":
                    activate_chrome()
                return page

    page = context.new_page()
    page.goto(CHATGPT_URL, wait_until="domcontentloaded")

    if browser_mode == "cdp":
        return page

    page.wait_for_load_state("networkidle", timeout=30_000)
    return page


def activate_chrome() -> None:
    if platform.system() != "Darwin":
        return

    subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to activate'],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def prompt_box_timeout(browser_mode: BrowserMode) -> int:
    if browser_mode == "cdp":
        return 5_000
    return 15_000


def type_and_submit(prompt_box, prompt: str, browser_mode: BrowserMode) -> None:
    if browser_mode == "cdp":
        prompt_box.click()
        prompt_box.fill(prompt)
        prompt_box.press("Enter")
        return

    prompt_box.click()
    sleep(0.5)
    prompt_box.press_sequentially(prompt, delay=PERSISTENT_TYPE_DELAY_MS)
    sleep(0.5)
    prompt_box.press("Enter")


def find_prompt_box(page, timeout: int):
    selectors = [
        "[data-testid='prompt-textarea']",
        "#prompt-textarea",
        "textarea[placeholder*='Message']",
        "div[contenteditable='true']",
    ]

    for selector in selectors:
        prompt_box = page.locator(selector).first
        try:
            prompt_box.wait_for(state="visible", timeout=timeout)
            return prompt_box
        except Exception:
            continue

    page.wait_for_selector(",".join(selectors), state="visible", timeout=timeout)
    return page.locator(",".join(selectors)).first
