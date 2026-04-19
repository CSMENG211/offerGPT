from dataclasses import dataclass
from pathlib import Path
import platform
import subprocess
from time import sleep

from loguru import logger

from constants import (
    CHATGPT_URL,
    DEFAULT_CDP_URL,
)

CHATGPT_COLOR_SCHEME = "dark"
CDP_BROWSER_PROFILE_MARKER = ".secondvoice/cdp-browser-profile"
SECONDVOICE_CHATGPT_TAB_NAME = "secondvoice-chatgpt"
SECONDVOICE_BADGE_ID = "secondvoice-tab-badge"
SECONDVOICE_TITLE_PREFIX = "SecondVoice"


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
    cdp_url: str = DEFAULT_CDP_URL,
) -> bool:
    """Open ChatGPT, place the prompt into the composer, and submit it."""
    if not prompt.strip():
        logger.info("Skipping ChatGPT submission because the transcript is empty.")
        return False

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        session = connect_to_cdp_browser(playwright, cdp_url)

        try:
            page = open_chatgpt_page(session.context)
            stabilize_chatgpt_theme(page)

            try:
                prompt_box = find_prompt_box(page, timeout=5_000)
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
                    return False

            fill_prompt(prompt_box, prompt)
            submit_prompt(page, prompt_box, wait_for_upload=has_photo)
            logger.info("Submitted transcript to ChatGPT.")
            activate_chrome()
            return True
        except PlaywrightTimeoutError as exc:
            logger.error("Could not find the ChatGPT prompt box.")
            logger.error("If this is the first run, log in to ChatGPT in the opened browser, then run again.")
            raise SystemExit(1) from exc
        finally:
            session.close()


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


def open_chatgpt_page(context):
    """Reuse the dedicated SecondVoice ChatGPT tab or open one when needed."""
    for page in context.pages:
        if page.url.startswith(CHATGPT_URL) and is_secondvoice_chatgpt_page(page):
            logger.info("Reusing dedicated SecondVoice ChatGPT tab.")
            mark_secondvoice_chatgpt_page(page)
            page.bring_to_front()
            activate_chrome()
            return page

    page = context.new_page()
    page.goto(CHATGPT_URL, wait_until="domcontentloaded")
    mark_secondvoice_chatgpt_page(page)
    return page


def is_secondvoice_chatgpt_page(page) -> bool:
    """Return whether a ChatGPT tab belongs to SecondVoice automation."""
    try:
        return page.evaluate(
            """
            (name) => window.name === name || sessionStorage.getItem(name) === "1"
            """,
            SECONDVOICE_CHATGPT_TAB_NAME,
        )
    except Exception as exc:
        logger.debug("Could not inspect ChatGPT tab marker: {}", exc)
        return False


def mark_secondvoice_chatgpt_page(page) -> None:
    """Mark one ChatGPT tab as the dedicated SecondVoice automation tab."""
    try:
        page.evaluate(
            """
            ({ name, badgeId, titlePrefix }) => {
              window.name = name;
              sessionStorage.setItem(name, "1");

              const updateTitle = () => {
                if (!document.title.startsWith(`${titlePrefix} - `)) {
                  document.title = `${titlePrefix} - ${document.title}`;
                }
              };
              updateTitle();
              window.__secondvoiceTitleTimer ||= window.setInterval(updateTitle, 1000);

              let badge = document.getElementById(badgeId);
              if (!badge) {
                badge = document.createElement("div");
                badge.id = badgeId;
                badge.textContent = titlePrefix;
                Object.assign(badge.style, {
                  position: "fixed",
                  right: "12px",
                  bottom: "12px",
                  zIndex: "2147483647",
                  padding: "6px 8px",
                  border: "1px solid rgba(255, 255, 255, 0.22)",
                  borderRadius: "6px",
                  background: "rgba(16, 16, 16, 0.86)",
                  color: "white",
                  font: "12px system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
                  pointerEvents: "none",
                });
                document.body.appendChild(badge);
              }
            }
            """,
            {
                "name": SECONDVOICE_CHATGPT_TAB_NAME,
                "badgeId": SECONDVOICE_BADGE_ID,
                "titlePrefix": SECONDVOICE_TITLE_PREFIX,
            },
        )
    except Exception as exc:
        logger.debug("Could not mark SecondVoice ChatGPT tab: {}", exc)


def activate_chrome() -> None:
    """Bring the automation Chrome process to the foreground on macOS."""
    if platform.system() != "Darwin":
        return

    pid = automation_chrome_pid()
    if pid is not None and activate_process(pid):
        return

    subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to activate'],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def automation_chrome_pid() -> int | None:
    """Return the main Chrome PID for the CDP automation profile."""
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if (
            "/Google Chrome.app/Contents/MacOS/Google Chrome" in line
            and "--remote-debugging-port=9222" in line
            and CDP_BROWSER_PROFILE_MARKER in line
        ):
            pid_text = line.strip().split(maxsplit=1)[0]
            try:
                return int(pid_text)
            except ValueError:
                return None

    return None


def activate_process(pid: int) -> bool:
    """Activate one macOS process by PID through System Events."""
    result = subprocess.run(
        [
            "osascript",
            "-e",
            (
                'tell application "System Events" to set frontmost of '
                f"(first process whose unix id is {pid}) to true"
            ),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def stabilize_chatgpt_theme(page) -> None:
    """Keep ChatGPT's visual theme stable during automation."""
    page.emulate_media(color_scheme=CHATGPT_COLOR_SCHEME)
    try:
        page.evaluate(
            """
            (theme) => {
              for (const key of Object.keys(localStorage)) {
                if (key.startsWith("oai/apps/chatTheme/")) {
                  localStorage.setItem(key, JSON.stringify(theme));
                }
              }
              document.documentElement.classList.remove("light", "dark");
              document.documentElement.classList.add(theme);
              document.documentElement.style.colorScheme = theme;
            }
            """,
            CHATGPT_COLOR_SCHEME,
        )
    except Exception as exc:
        logger.debug("Could not stabilize ChatGPT theme: {}", exc)


def fill_prompt(prompt_box, prompt: str) -> None:
    """Fill the prompt box without submitting the message."""
    prompt_box.click()
    prompt_box.fill(prompt)


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
