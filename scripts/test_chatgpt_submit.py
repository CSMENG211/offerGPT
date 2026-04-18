import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offergpt.browser import submit_to_chatgpt


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a stdin prompt to ChatGPT.")
    parser.add_argument(
        "--browser-mode",
        choices=("persistent", "cdp"),
        default="cdp",
        help="Browser automation mode. Default: cdp",
    )
    parser.add_argument(
        "--new-tab",
        action="store_true",
        help="Open a new ChatGPT tab instead of reusing an existing one.",
    )
    args = parser.parse_args()

    prompt = read_prompt()
    submit_to_chatgpt(
        prompt,
        browser_mode=args.browser_mode,
        new_tab=args.new_tab,
    )


def read_prompt() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    print("Enter the prompt to send to ChatGPT:")
    return input("> ").strip()


if __name__ == "__main__":
    main()
