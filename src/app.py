import queue
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from audio import capture_utterance, record_until_enter, stream_utterance_segments
from browser import BrowserMode, submit_to_chatgpt
from constants import (
    DEFAULT_MAX_RECORD_SECONDS,
    DEFAULT_PROMPT_MODE,
    DEFAULT_QUESTION_START_PATTERN,
    DEFAULT_QUESTION_TRIGGER_MODE,
    DEFAULT_SILENCE_SECONDS,
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_TRANSCRIPTION_MODEL,
    PROMPTS,
    PromptMode,
    STREAM_SILENCE_SECONDS,
)
from question_triggers import extract_question_prompt
from transcription import LocalTranscriber, transcribe


@dataclass(frozen=True)
class RuntimeOptions:
    """Options selected by the command-line interface."""

    ask_chatgpt: bool = True
    browser_mode: BrowserMode = "cdp"
    listen: bool = True
    prompt_mode: PromptMode = DEFAULT_PROMPT_MODE


def run(options: RuntimeOptions) -> None:
    """Run either continuous listen mode or a one-shot recording."""
    if options.prompt_mode == "stream":
        stream_loop(options)
        return

    if options.listen:
        batch_loop(options)
        return

    transcript = record_and_transcribe_once()

    logger.info("Transcript:\n{}", transcript.strip() or "(No speech detected.)")

    if options.ask_chatgpt:
        submit_prompt(transcript, options, include_mode_prompt=True)


def record_and_transcribe_once() -> str:
    """Record one manually-delimited utterance and return its transcript."""
    input("Press ENTER to start recording.")

    with tempfile.TemporaryDirectory(prefix="secondvoice-") as temp_dir:
        audio_path = Path(temp_dir) / "recording.wav"
        record_until_enter(audio_path)

        logger.info("Transcribing locally with faster-whisper ({})...", DEFAULT_TRANSCRIPTION_MODEL)
        return transcribe(audio_path, DEFAULT_TRANSCRIPTION_MODEL)


def batch_loop(options: RuntimeOptions) -> None:
    """Continuously capture utterances, extract prompts, and optionally submit them."""
    transcriber = LocalTranscriber(DEFAULT_TRANSCRIPTION_MODEL)
    is_first_submission = True

    print_batch_mode_banner(options.prompt_mode)

    try:
        while True:
            transcript = capture_and_transcribe_utterance(transcriber)
            print_transcript(transcript)

            prompt = extract_question_prompt(
                transcript,
                DEFAULT_QUESTION_START_PATTERN,
                DEFAULT_QUESTION_TRIGGER_MODE,
            )
            if not should_handle_prompt(prompt):
                continue

            logger.info("Triggered prompt:\n{}", prompt)

            if options.ask_chatgpt:
                submit_prompt(
                    prompt,
                    options,
                    include_mode_prompt=is_first_submission,
                )
                is_first_submission = False
            logger.info("")
    except KeyboardInterrupt:
        logger.info("Stopped listening.")


def stream_loop(options: RuntimeOptions) -> None:
    """Continuously capture interview answers and submit each segment for feedback."""
    is_first_submission = True

    print_stream_mode_banner()

    with tempfile.TemporaryDirectory(prefix="secondvoice-eval-") as temp_dir:
        segment_queue: queue.Queue[Path | Exception] = queue.Queue()
        stop_event = threading.Event()
        recorder = start_stream_recorder(
            Path(temp_dir),
            segment_queue,
            stop_event,
        )

        try:
            transcriber = LocalTranscriber(DEFAULT_TRANSCRIPTION_MODEL)
            while True:
                audio_path = next_stream_segment(segment_queue)
                if audio_path is None:
                    continue

                submitted = process_stream_segment(
                    audio_path,
                    transcriber,
                    options,
                    include_mode_prompt=is_first_submission,
                )
                if submitted:
                    is_first_submission = False
        except KeyboardInterrupt:
            logger.info("Stopping stream mode...")
        finally:
            stop_event.set()
            recorder.join()
            logger.info("Stopped stream mode.")


def start_stream_recorder(
    output_dir: Path,
    segment_queue: queue.Queue[Path | Exception],
    stop_event: threading.Event,
) -> threading.Thread:
    """Start the background recorder that feeds completed segments into a queue."""
    recorder = threading.Thread(
        target=stream_utterance_segments,
        args=(
            output_dir,
            segment_queue,
            stop_event,
            STREAM_SILENCE_SECONDS,
            DEFAULT_SILENCE_THRESHOLD,
        ),
    )
    recorder.start()
    return recorder


def next_stream_segment(segment_queue: queue.Queue[Path | Exception]) -> Path | None:
    """Return the next completed stream segment, or None while waiting."""
    try:
        item = segment_queue.get(timeout=0.2)
    except queue.Empty:
        return None

    if isinstance(item, Exception):
        raise item

    return item


def process_stream_segment(
    audio_path: Path,
    transcriber: LocalTranscriber,
    options: RuntimeOptions,
    include_mode_prompt: bool,
) -> bool:
    """Transcribe one stream segment and optionally submit it for feedback."""
    transcript = transcriber.transcribe(audio_path)
    audio_path.unlink(missing_ok=True)
    print_transcript(transcript)

    if not transcript:
        logger.info("No speech detected. Listening again.")
        return False

    if options.ask_chatgpt:
        submit_to_chatgpt(
            build_stream_prompt(transcript, include_mode_prompt),
            browser_mode=options.browser_mode,
        )
    logger.info("")
    return options.ask_chatgpt


def capture_and_transcribe_utterance(transcriber: LocalTranscriber) -> str:
    """Capture one speech segment using silence detection and transcribe it."""
    with tempfile.TemporaryDirectory(prefix="secondvoice-") as temp_dir:
        audio_path = Path(temp_dir) / "utterance.wav"
        capture_utterance(
            audio_path,
            silence_seconds=DEFAULT_SILENCE_SECONDS,
            silence_threshold=DEFAULT_SILENCE_THRESHOLD,
            max_record_seconds=DEFAULT_MAX_RECORD_SECONDS,
        )
        return transcriber.transcribe(audio_path)


def submit_prompt(prompt: str, options: RuntimeOptions, include_mode_prompt: bool) -> None:
    """Submit a prompt to ChatGPT, prepending mode instructions once per run."""
    submit_to_chatgpt(
        build_chatgpt_prompt(prompt, options.prompt_mode, include_mode_prompt),
        browser_mode=options.browser_mode,
    )


def build_chatgpt_prompt(
    prompt: str,
    prompt_mode: PromptMode,
    include_mode_prompt: bool,
) -> str:
    """Return the ChatGPT prompt with optional first-message mode instructions."""
    if not include_mode_prompt:
        return prompt

    return f"{PROMPTS[prompt_mode]}\n\nQuestion:\n{prompt}"


def build_stream_prompt(transcript: str, include_mode_prompt: bool) -> str:
    """Return a prompt that asks ChatGPT to evaluate an interview transcript segment."""
    if include_mode_prompt:
        return f"{PROMPTS['stream']}\n\nTranscript segment:\n{transcript}"

    return f"Evaluate this transcript segment:\n{transcript}"


def print_batch_mode_banner(prompt_mode: PromptMode) -> None:
    """Print the active batch-mode trigger settings."""
    logger.info("Batch mode is active.")
    logger.info("Audio start trigger: speech begins")
    logger.info("Audio stop trigger: {:g}s of silence", DEFAULT_SILENCE_SECONDS)
    logger.info("Max recording length: {:g}s", DEFAULT_MAX_RECORD_SECONDS)
    logger.info("Prompt preset: {}", prompt_mode)
    logger.info("Question trigger mode: {}", DEFAULT_QUESTION_TRIGGER_MODE)
    if DEFAULT_QUESTION_TRIGGER_MODE in ("phrase", "smart"):
        logger.info("Question start pattern: {!r}", DEFAULT_QUESTION_START_PATTERN)
    logger.info("Press Ctrl+C to stop.")


def print_stream_mode_banner() -> None:
    """Print the active stream-mode trigger settings."""
    logger.info("Stream mode is active.")
    logger.info("Audio start trigger: speech begins")
    logger.info("Segment trigger: {:g}s of silence", STREAM_SILENCE_SECONDS)
    logger.info("Recording continues while segments are transcribed and submitted")
    logger.info("Question detection: disabled")
    logger.info("Press Ctrl+C to stop.")


def print_transcript(transcript: str) -> None:
    """Print the transcript from the most recent captured utterance."""
    logger.info("Heard:\n{}", transcript.strip() or "(No speech detected.)")


def should_handle_prompt(prompt: str | None) -> bool:
    """Return whether a detected prompt is non-empty and ready for handling."""
    if prompt is None:
        logger.info("No interview prompt detected. Listening again.")
        return False

    if not prompt:
        logger.info("Prompt detector fired, but the prompt was empty. Listening again.")
        return False

    return True
