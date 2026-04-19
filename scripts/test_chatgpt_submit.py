import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import build_stream_prompt, latest_interview_photo
from browser import submit_to_chatgpt
from logging_config import configure_logging


def main() -> None:
    """Read a transcript segment and submit it to ChatGPT through browser automation."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Submit a stdin transcript segment to ChatGPT.")
    parser.add_argument(
        "--browser",
        choices=("persistent", "cdp"),
        default="cdp",
        help="Browser automation mode. Default: cdp",
    )
    parser.add_argument(
        "--upload-photo",
        action="store_true",
        help="Upload the latest photo from /Users/flora/interview/ with the prompt.",
    )
    args = parser.parse_args()

    prompt = read_prompt()
    photo_path = latest_interview_photo() if args.upload_photo else None
    submit_to_chatgpt(
        build_stream_prompt(
            prompt,
            include_mode_prompt=True,
            include_photo_context=photo_path is not None,
        ),
        photo_path=photo_path,
        browser_mode=args.browser,
    )


def read_prompt() -> str:
    """Read a prompt from stdin or interactively from the terminal."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    return input("Enter the transcript segment to send to ChatGPT:\n> ").strip()


if __name__ == "__main__":
    main()
