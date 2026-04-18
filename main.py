import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from offergpt.audio import (
    capture_utterance,
    record_until_enter,
)
from offergpt.browser import submit_to_chatgpt
from offergpt.constants import (
    DEFAULT_MAX_RECORD_SECONDS,
    DEFAULT_QUESTION_START_PHRASES,
    DEFAULT_QUESTION_TRIGGER_MODE,
    DEFAULT_SILENCE_SECONDS,
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_TRANSCRIPTION_MODEL,
)
from offergpt.transcription import LocalTranscriber, transcribe
from offergpt.question_triggers import (
    extract_question_prompt,
)


def main() -> None:
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

    if args.listen:
        listen_loop(args)
        return

    transcript = record_and_transcribe_once(args)

    print("\nTranscript:")
    print(transcript.strip() or "(No speech detected.)")

    if args.ask_chatgpt:
        submit_to_chatgpt(
            transcript,
            browser_mode=args.browser_mode,
        )


def record_and_transcribe_once(args) -> str:
    print("Press ENTER to start recording.")
    input()

    with tempfile.TemporaryDirectory(prefix="offergpt-") as temp_dir:
        audio_path = Path(temp_dir) / "recording.wav"
        record_until_enter(audio_path, device=None)

        print(
            f"Transcribing locally with faster-whisper ({DEFAULT_TRANSCRIPTION_MODEL})...",
            flush=True,
        )
        return transcribe(audio_path, DEFAULT_TRANSCRIPTION_MODEL)


def listen_loop(args) -> None:
    question_start_phrases = list(DEFAULT_QUESTION_START_PHRASES)
    transcriber = LocalTranscriber(DEFAULT_TRANSCRIPTION_MODEL)

    print("Listen mode is active.")
    print("Audio start trigger: speech begins")
    print(f"Audio stop trigger: {DEFAULT_SILENCE_SECONDS:g}s of silence")
    print(f"Question trigger mode: {DEFAULT_QUESTION_TRIGGER_MODE}")
    if DEFAULT_QUESTION_TRIGGER_MODE in ("phrase", "smart"):
        print(
            "Question start phrases: "
            + ", ".join(repr(phrase) for phrase in question_start_phrases)
        )
    print("Press Ctrl+C to stop.")

    try:
        while True:
            with tempfile.TemporaryDirectory(prefix="offergpt-") as temp_dir:
                audio_path = Path(temp_dir) / "utterance.wav"
                capture_utterance(
                    audio_path,
                    device=None,
                    silence_seconds=DEFAULT_SILENCE_SECONDS,
                    silence_threshold=DEFAULT_SILENCE_THRESHOLD,
                    max_record_seconds=DEFAULT_MAX_RECORD_SECONDS,
                )

                transcript = transcriber.transcribe(audio_path)

            print("\nHeard:")
            print(transcript.strip() or "(No speech detected.)")

            prompt = extract_question_prompt(
                transcript,
                question_start_phrases,
                DEFAULT_QUESTION_TRIGGER_MODE,
            )
            if prompt is None:
                print("No interview prompt detected. Listening again.\n")
                continue

            if not prompt:
                print("Prompt detector fired, but the prompt was empty. Listening again.\n")
                continue

            print("\nTriggered prompt:")
            print(prompt)

            if args.ask_chatgpt:
                submit_to_chatgpt(
                    prompt,
                    browser_mode=args.browser_mode,
                )
            print()
    except KeyboardInterrupt:
        print("\nStopped listening.")


if __name__ == "__main__":
    main()
