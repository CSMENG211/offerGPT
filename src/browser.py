from dataclasses import dataclass
from pathlib import Path
import platform
import subprocess
from time import sleep
from typing import Literal

from loguru import logger

from constants import (
    CHATGPT_URL,
    DEFAULT_BROWSER_PROFILE,
    DEFAULT_CDP_URL,
    PERSISTENT_TYPE_DELAY_MS,
)

BrowserMode = Literal["persistent", "cdp"]


@dataclass
class BrowserSession:
    """Browser resources opened or attached for one ChatGPT submission."""

    context: object
    close_browser: bool = True
    browser: object | None = None

    def close(self) -> None:
        """Close browser resources that this process owns."""
        if self.close_browser:
            self.context.close()


def submit_to_chatgpt(
    prompt: str,
    photo_path: Path | None = None,
    profile_dir: Path = DEFAULT_BROWSER_PROFILE,
    browser_mode: BrowserMode = "cdp",
    cdp_url: str = DEFAULT_CDP_URL,
) -> None:
    """Open ChatGPT, place the prompt into the composer, and submit it."""
    if not prompt.strip():
        logger.info("Skipping ChatGPT submission because the transcript is empty.")
        return

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        session = open_browser_session(playwright, profile_dir, browser_mode, cdp_url)

        try:
            page = open_chatgpt_page(session.context, browser_mode)

            try:
                prompt_box = find_prompt_box(page, timeout=prompt_box_timeout(browser_mode))
            except PlaywrightTimeoutError:
                logger.warning("Could not find the ChatGPT prompt box yet.")
                logger.warning("If ChatGPT is asking you to log in, finish logging in inside the browser.")
                input("Press ENTER here after ChatGPT is open and ready for a prompt.")
                page.goto(CHATGPT_URL, wait_until="domcontentloaded")
                prompt_box = find_prompt_box(page, timeout=60_000)

            has_photo = photo_path is not None
            if has_photo:
                if not attach_file(page, photo_path):
                    logger.error("Skipping ChatGPT submission because the photo could not be attached.")
                    return

            fill_prompt(prompt_box, prompt, browser_mode)
            submit_prompt(page, prompt_box, wait_for_upload=has_photo)
            logger.info("Submitted transcript to ChatGPT.")
            if browser_mode == "cdp":
                activate_chrome()
            if session.close_browser:
                input("Browser is open. Press ENTER here when you are ready to close it.")
        except PlaywrightTimeoutError as exc:
            logger.error("Could not find the ChatGPT prompt box.")
            logger.error("If this is the first run, log in to ChatGPT in the opened browser, then run again.")
            raise SystemExit(1) from exc
        finally:
            session.close()


def open_browser_session(
    playwright,
    profile_dir: Path,
    browser_mode: BrowserMode,
    cdp_url: str,
) -> BrowserSession:
    """Open a browser context using the selected automation mode."""
    if browser_mode == "cdp":
        return connect_to_cdp_browser(playwright, cdp_url)
    return launch_persistent_browser(playwright, profile_dir)


def launch_persistent_browser(playwright, profile_dir: Path) -> BrowserSession:
    """Launch a visible Chromium browser with a reusable profile directory."""
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
        logger.info("Opening ChatGPT with installed Google Chrome...")
        context = playwright.chromium.launch_persistent_context(
            channel="chrome",
            **launch_options,
        )
    except Exception as exc:
        logger.warning("Could not launch installed Chrome: {}", exc)
        logger.info("Falling back to Playwright Chromium...")
        context = playwright.chromium.launch_persistent_context(**launch_options)

    return BrowserSession(context=context, close_browser=True)


def connect_to_cdp_browser(playwright, cdp_url: str) -> BrowserSession:
    """Connect to an already-running Chrome instance over CDP."""
    logger.info("Connecting to Chrome over CDP at {}...", cdp_url)
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:
        logger.error("Could not connect to Chrome over CDP: {}", exc)
        logger.error(
            "Launch an automation-friendly Chrome first with:\n"
            "  open -na 'Google Chrome' --args \\\n"
            "    --remote-debugging-port=9222 \\\n"
            "    --user-data-dir=$HOME/.secondvoice/cdp-browser-profile"
        )
        raise SystemExit(1) from exc

    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context(no_viewport=True)

    # Leave the CDP browser running so you can stay logged in between tests.
    return BrowserSession(context=context, close_browser=False, browser=browser)


def open_chatgpt_page(context, browser_mode: BrowserMode):
    """Reuse an existing ChatGPT tab or open one when needed."""
    for page in context.pages:
        if page.url.startswith(CHATGPT_URL):
            logger.info("Reusing existing ChatGPT tab.")
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
    """Bring Google Chrome to the foreground on macOS."""
    if platform.system() != "Darwin":
        return

    subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to activate'],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def prompt_box_timeout(browser_mode: BrowserMode) -> int:
    """Return how long to wait for ChatGPT's prompt box in each browser mode."""
    if browser_mode == "cdp":
        return 5_000
    return 15_000


def fill_prompt(prompt_box, prompt: str, browser_mode: BrowserMode) -> None:
    """Fill the prompt box without submitting the message."""
    if browser_mode == "cdp":
        prompt_box.click()
        prompt_box.fill(prompt)
        return

    prompt_box.click()
    sleep(0.5)
    prompt_box.press_sequentially(prompt, delay=PERSISTENT_TYPE_DELAY_MS)
    sleep(0.5)


def submit_prompt(page, prompt_box, wait_for_upload: bool = False) -> None:
    """Submit the composed message after ChatGPT enables sending."""
    if wait_for_upload:
        wait_for_attachment_upload(page)

    send_button = find_send_button(page)
    if send_button is None:
        logger.warning("Could not find ChatGPT send button; falling back to Enter.")
        prompt_box.press("Enter")
        return

    send_button.click(timeout=30_000)


def find_send_button(page):
    """Return ChatGPT's send button when one of the known selectors is visible."""
    selectors = [
        "[data-testid='send-button']",
        "button[aria-label='Send prompt']",
        "button[aria-label*='Send']",
    ]

    for selector in selectors:
        button = page.locator(selector).first
        try:
            button.wait_for(state="visible", timeout=2_000)
            return button
        except Exception:
            continue

    return None


def attach_file(page, file_path: Path) -> bool:
    """Attach a local file to the current ChatGPT composer."""
    if not file_path.exists() or not file_path.is_file():
        logger.warning("Skipping ChatGPT photo upload because the file is missing: {}", file_path)
        return False

    logger.info("Uploading interview photo to ChatGPT: {}", file_path)

    file_inputs = page.locator("input[type='file']")
    if file_inputs.count() > 0:
        file_inputs.last.set_input_files(str(file_path))
        wait_for_attachment_upload(page)
        return True

    attach_selectors = [
        "[data-testid='composer-plus-btn']",
        "button[aria-label*='Attach']",
        "button[aria-label*='Upload']",
        "button:has-text('Attach')",
        "button:has-text('Upload')",
    ]

    for selector in attach_selectors:
        button = page.locator(selector).first
        try:
            button.wait_for(state="visible", timeout=2_000)
            with page.expect_file_chooser(timeout=5_000) as chooser_info:
                button.click()
            chooser_info.value.set_files(str(file_path))
            wait_for_attachment_upload(page)
            return True
        except Exception:
            continue

    logger.warning("Could not find a ChatGPT file upload control.")
    return False


def wait_for_attachment_upload(page, timeout: int = 30_000) -> None:
    """Wait briefly for ChatGPT to finish accepting the selected file."""
    try:
        page.get_by_text("Uploading", exact=False).first.wait_for(state="hidden", timeout=timeout)
    except Exception:
        # Some ChatGPT builds do not expose upload text; the send button click
        # still auto-waits for the composer to become actionable.
        sleep(1)


def find_prompt_box(page, timeout: int):
    """Find the current ChatGPT message composer using known selectors."""
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
