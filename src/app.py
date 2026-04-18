import tempfile
from dataclasses import dataclass
from pathlib import Path

from audio import capture_utterance, record_until_enter
from browser import BrowserMode, submit_to_chatgpt
from constants import (
    DEFAULT_MAX_RECORD_SECONDS,
    DEFAULT_QUESTION_START_PHRASES,
    DEFAULT_QUESTION_TRIGGER_MODE,
    DEFAULT_SILENCE_SECONDS,
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_TRANSCRIPTION_MODEL,
)
from question_triggers import extract_question_prompt
from transcription import LocalTranscriber, transcribe


@dataclass(frozen=True)
class RuntimeOptions:
    """Options selected by the command-line interface."""

    ask_chatgpt: bool = True
    browser_mode: BrowserMode = "cdp"
    listen: bool = True


def run(options: RuntimeOptions) -> None:
    """Run either continuous listen mode or a one-shot recording."""
    if options.listen:
        listen_loop(options)
        return

    transcript = record_and_transcribe_once()

    print("\nTranscript:")
    print(transcript.strip() or "(No speech detected.)")

    if options.ask_chatgpt:
        submit_to_chatgpt(transcript, browser_mode=options.browser_mode)


def record_and_transcribe_once() -> str:
    """Record one manually-delimited utterance and return its transcript."""
    print("Press ENTER to start recording.")
    input()

    with tempfile.TemporaryDirectory(prefix="offergpt-") as temp_dir:
        audio_path = Path(temp_dir) / "recording.wav"
        record_until_enter(audio_path)

        print(
            f"Transcribing locally with faster-whisper ({DEFAULT_TRANSCRIPTION_MODEL})...",
            flush=True,
        )
        return transcribe(audio_path, DEFAULT_TRANSCRIPTION_MODEL)


def listen_loop(options: RuntimeOptions) -> None:
    """Continuously capture utterances, extract prompts, and optionally submit them."""
    question_start_phrases = list(DEFAULT_QUESTION_START_PHRASES)
    transcriber = LocalTranscriber(DEFAULT_TRANSCRIPTION_MODEL)

    print_listen_mode_banner(question_start_phrases)

    try:
        while True:
            transcript = capture_and_transcribe_utterance(transcriber)
            print_transcript(transcript)

            prompt = extract_question_prompt(
                transcript,
                question_start_phrases,
                DEFAULT_QUESTION_TRIGGER_MODE,
            )
            if not should_handle_prompt(prompt):
                continue

            print("\nTriggered prompt:")
            print(prompt)

            if options.ask_chatgpt:
                submit_to_chatgpt(prompt, browser_mode=options.browser_mode)
            print()
    except KeyboardInterrupt:
        print("\nStopped listening.")


def capture_and_transcribe_utterance(transcriber: LocalTranscriber) -> str:
    """Capture one speech segment using silence detection and transcribe it."""
    with tempfile.TemporaryDirectory(prefix="offergpt-") as temp_dir:
        audio_path = Path(temp_dir) / "utterance.wav"
        capture_utterance(
            audio_path,
            silence_seconds=DEFAULT_SILENCE_SECONDS,
            silence_threshold=DEFAULT_SILENCE_THRESHOLD,
            max_record_seconds=DEFAULT_MAX_RECORD_SECONDS,
        )
        return transcriber.transcribe(audio_path)


def print_listen_mode_banner(question_start_phrases: list[str]) -> None:
    """Print the active listen-mode trigger settings."""
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


def print_transcript(transcript: str) -> None:
    """Print the transcript from the most recent captured utterance."""
    print("\nHeard:")
    print(transcript.strip() or "(No speech detected.)")


def should_handle_prompt(prompt: str | None) -> bool:
    """Return whether a detected prompt is non-empty and ready for handling."""
    if prompt is None:
        print("No interview prompt detected. Listening again.\n")
        return False

    if not prompt:
        print("Prompt detector fired, but the prompt was empty. Listening again.\n")
        return False

    return True
