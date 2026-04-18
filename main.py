import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app import RuntimeOptions, run


def main() -> None:
    """Parse command-line options and start offerGPT."""
    run(parse_args())


def parse_args() -> RuntimeOptions:
    """Parse CLI flags into runtime options."""
    parser = argparse.ArgumentParser(description="Record microphone audio and transcribe it.")
    parser.add_argument(
        "--no-ask-chatgpt",
        action="store_false",
        dest="ask_chatgpt",
        default=True,
        help="Transcribe without submitting the prompt to ChatGPT.",
    )
    parser.add_argument(
        "--browser-mode",
        choices=("persistent", "cdp"),
        default="cdp",
        help="Browser automation mode for ChatGPT submission. Default: cdp",
    )
    parser.add_argument(
        "--no-listen",
        action="store_false",
        dest="listen",
        default=True,
        help="Record one utterance manually instead of continuously listening.",
    )
    args = parser.parse_args()
    return RuntimeOptions(
        ask_chatgpt=args.ask_chatgpt,
        browser_mode=args.browser_mode,
        listen=args.listen,
    )


if __name__ == "__main__":
    main()
