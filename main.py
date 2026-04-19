import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app import RuntimeOptions, run
from constants import DEFAULT_CDP_URL
from endpoint_detector import DEFAULT_ENDPOINT_MODEL, OLLAMA_CHAT_URL
from logging_config import configure_logging
from loguru import logger


def main() -> None:
    """Parse command-line options and start SecondVoice."""
    configure_logging()
    options = parse_args()
    check_runtime_dependencies(options)
    run(options)


def parse_args() -> RuntimeOptions:
    """Parse CLI flags into runtime options."""
    parser = argparse.ArgumentParser(
        description="Stream mock-interview audio segments to ChatGPT."
    )
    parser.add_argument(
        "--no-ask",
        action="store_false",
        dest="ask_chatgpt",
        default=True,
        help="Transcribe without submitting the prompt to ChatGPT.",
    )
    parser.add_argument(
        "--enroll",
        action="store_true",
        help="Record prompted interviewee voice samples and save the voice profile.",
    )
    parser.add_argument(
        "--photo-mode",
        choices=("none", "test", "live"),
        default="none",
        help=(
            "Control interview photo capture and upload: "
            "none disables all photo capture and upload; "
            "test captures to /Users/flora/interview/test.jpg; "
            "live captures to /Users/flora/interview/live.jpg. Default: none."
        ),
    )
    args = parser.parse_args()
    return RuntimeOptions(
        ask_chatgpt=args.ask_chatgpt,
        enroll_me=args.enroll,
        photo_mode=args.photo_mode,
    )


def check_runtime_dependencies(options: RuntimeOptions) -> None:
    """Abort early when required local services are not ready."""
    if options.enroll_me:
        return

    logger.info("Running startup dependency checks...")
    checks_passed = True

    if not ollama_model_is_ready():
        checks_passed = False

    if options.ask_chatgpt and not cdp_browser_is_ready():
        checks_passed = False

    if not checks_passed:
        logger.error("Startup checks failed. Aborting before microphone capture.")
        raise SystemExit(1)

    logger.info("Startup dependency checks passed.")


def ollama_model_is_ready() -> bool:
    """Return whether Ollama is reachable and has the endpoint model installed."""
    tags_url = OLLAMA_CHAT_URL.rsplit("/", 1)[0] + "/tags"
    try:
        with urlopen(tags_url, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as error:
        logger.error("Could not reach Ollama at {}: {}", tags_url, error)
        logger.error("Start Ollama with: ollama serve")
        return False

    model_names = {model.get("name") for model in body.get("models", [])}
    if DEFAULT_ENDPOINT_MODEL not in model_names:
        logger.error("Ollama model {} is not installed.", DEFAULT_ENDPOINT_MODEL)
        logger.error("Install it with: ollama pull {}", DEFAULT_ENDPOINT_MODEL)
        return False

    logger.info("Ollama ready: {}", DEFAULT_ENDPOINT_MODEL)
    return True


def cdp_browser_is_ready() -> bool:
    """Return whether Chrome is reachable over the configured CDP port."""
    version_url = f"{DEFAULT_CDP_URL}/json/version"
    try:
        with urlopen(version_url, timeout=2) as response:
            response.read()
    except (OSError, URLError) as error:
        logger.error("Could not reach Chrome CDP at {}: {}", version_url, error)
        logger.error(
            "Start Chrome with:\n"
            "  open -na 'Google Chrome' --args \\\n"
            "    --remote-debugging-port=9222 \\\n"
            "    --user-data-dir=$HOME/.secondvoice/cdp-browser-profile"
        )
        return False

    logger.info("Chrome CDP ready: {}", DEFAULT_CDP_URL)
    return True


if __name__ == "__main__":
    main()
