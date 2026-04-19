import queue
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from audio import stream_utterance_segments
from browser import BrowserMode, submit_to_chatgpt
from constants import (
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_TRANSCRIPTION_MODEL,
    STREAM_PROMPT,
    STREAM_SILENCE_SECONDS,
)
from transcription import LocalTranscriber


@dataclass(frozen=True)
class RuntimeOptions:
    """Options selected by the command-line interface."""

    ask_chatgpt: bool = True
    browser_mode: BrowserMode = "cdp"


def run(options: RuntimeOptions) -> None:
    """Run continuous stream mode."""
    stream_loop(options)


def stream_loop(options: RuntimeOptions) -> None:
    """Continuously capture interview segments and submit each segment for feedback."""
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


def build_stream_prompt(transcript: str, include_mode_prompt: bool) -> str:
    """Return a prompt that asks ChatGPT to evaluate an interview transcript segment."""
    if include_mode_prompt:
        return f"{STREAM_PROMPT}\n\nClassify and process this transcript segment:\n{transcript}"

    return f"Classify and process this transcript segment:\n{transcript}"


def print_stream_mode_banner() -> None:
    """Print the active stream-mode trigger settings."""
    logger.info("Stream mode is active.")
    logger.info("Audio start trigger: speech begins")
    logger.info("Segment trigger: {:g}s of silence", STREAM_SILENCE_SECONDS)
    logger.info("Recording continues while segments are transcribed and submitted")
    logger.info("Segment role detection: delegated to ChatGPT")
    logger.info("Press Ctrl+C to stop.")


def print_transcript(transcript: str) -> None:
    """Print the transcript from the most recent captured utterance."""
    logger.info("Heard:\n{}", transcript.strip() or "(No speech detected.)")
