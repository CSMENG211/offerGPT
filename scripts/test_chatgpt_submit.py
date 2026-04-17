import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offergpt.browser import DEFAULT_CDP_URL, submit_to_chatgpt


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a fixed test prompt to ChatGPT.")
    parser.add_argument(
        "--browser-mode",
        choices=("persistent", "cdp"),
        default="persistent",
        help="Browser automation mode. Default: persistent",
    )
    parser.add_argument(
        "--cdp-url",
        default=DEFAULT_CDP_URL,
        help=f"Chrome DevTools URL for --browser-mode cdp. Default: {DEFAULT_CDP_URL}",
    )
    args = parser.parse_args()

    submit_to_chatgpt(
        "What is 1 + 1?",
        browser_mode=args.browser_mode,
        cdp_url=args.cdp_url,
    )


if __name__ == "__main__":
    main()
