from dataclasses import dataclass
import platform
import subprocess

from loguru import logger


CDP_BROWSER_PROFILE_MARKER = ".secondvoice/cdp-browser-profile"


@dataclass
class BrowserSession:
    """Browser resources opened or attached for one automation action."""

    context: object
    close_browser: bool = True
    browser: object | None = None

    def close(self) -> None:
        """Close browser resources that this process owns."""
        if self.close_browser:
            self.context.close()


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
