import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app import RuntimeOptions, run
from logging_config import configure_logging


def main() -> None:
    """Parse command-line options and start SecondVoice."""
    configure_logging()
    run(parse_args())


def parse_args() -> RuntimeOptions:
    """Parse CLI flags into runtime options."""
    parser = argparse.ArgumentParser(description="Listen for questions and send answers to GPT.")
    parser.set_defaults(prompt_preset="batch")
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
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mode",
        choices=("generic", "batch", "stream"),
        dest="prompt_preset",
        help=(
            "Preset to run. generic and batch use batch capture; stream uses "
            "continuous stream capture. Default: batch"
        ),
    )
    mode_group.add_argument(
        "--generic",
        action="store_const",
        const="generic",
        dest="prompt_preset",
        help="Use batch capture with the generic workplace-answer prompt.",
    )
    mode_group.add_argument(
        "--batch",
        action="store_const",
        const="batch",
        dest="prompt_preset",
        help="Use batch capture with the interview-help prompt.",
    )
    mode_group.add_argument(
        "--stream",
        action="store_const",
        const="stream",
        dest="prompt_preset",
        help=(
            "Continuously transcribe voice-triggered interview segments and "
            "submit them for evaluation."
        ),
    )
    args = parser.parse_args()
    return RuntimeOptions(
        ask_chatgpt=args.ask_chatgpt,
        browser_mode=args.browser_mode,
        listen=args.listen,
        prompt_mode=args.prompt_preset,
    )


if __name__ == "__main__":
    main()
