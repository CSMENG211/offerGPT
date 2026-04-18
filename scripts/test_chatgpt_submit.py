import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser import submit_to_chatgpt
from constants import DEFAULT_ANSWER_MODE
from app import build_chatgpt_prompt


def main() -> None:
    """Read a prompt and submit it to ChatGPT through browser automation."""
    parser = argparse.ArgumentParser(description="Submit a stdin prompt to ChatGPT.")
    parser.add_argument(
        "--browser-mode",
        choices=("persistent", "cdp"),
        default="cdp",
        help="Browser automation mode. Default: cdp",
    )
    parser.add_argument(
        "--mode",
        choices=("generic", "helpful"),
        default=DEFAULT_ANSWER_MODE,
        help=f"Answer style to prepend to the prompt. Default: {DEFAULT_ANSWER_MODE}",
    )
    args = parser.parse_args()

    prompt = read_prompt()
    submit_to_chatgpt(
        build_chatgpt_prompt(prompt, args.mode, include_mode_prompt=True),
        browser_mode=args.browser_mode,
    )


def read_prompt() -> str:
    """Read a prompt from stdin or interactively from the terminal."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    print("Enter the prompt to send to ChatGPT:")
    return input("> ").strip()


if __name__ == "__main__":
    main()
