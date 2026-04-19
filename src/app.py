import queue
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from audio import capture_enrollment_utterance, stream_utterance_segments
from browser import BrowserMode, submit_to_chatgpt
from camera_photo import CameraCaptureError, take_photo
from constants import (
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_TRANSCRIPTION_MODEL,
    INTERVIEW_PHOTO_DIR,
    INTERVIEW_PHOTO_EXTENSIONS,
    PHOTO_CAPTURE_INTERVAL_SECONDS,
    SPEAKER_ENROLLMENT_MAX_SECONDS,
    SPEAKER_ENROLLMENT_PROMPTS,
    SPEAKER_ENROLLMENT_SILENCE_SECONDS,
    SPEAKER_PROFILE_EMBEDDING_PATH,
    SPEAKER_PROFILE_METADATA_PATH,
    STREAM_PROMPT,
    STREAM_SILENCE_SECONDS,
)
from speaker_id import SpeakerHint, SpeakerIdentifier
from transcription import LocalTranscriber


PHOTO_CONTEXT_PROMPT = (
    "Attached image context: the uploaded image is the current state of the "
    "problem board. Use it as visual context for the entire problem, and "
    "do not treat it as a separate question."
)


@dataclass(frozen=True)
class RuntimeOptions:
    """Options selected by the command-line interface."""

    ask_chatgpt: bool = True
    browser_mode: BrowserMode = "cdp"
    enroll_me: bool = False
    upload_photo: bool = False


def run(options: RuntimeOptions) -> None:
    """Run continuous stream mode."""
    if options.enroll_me:
        enroll_interviewee_voice()
        return

    stream_loop(options)


def enroll_interviewee_voice() -> None:
    """Record prompted enrollment clips and persist an interviewee voice profile."""
    logger.info("Starting interviewee voice enrollment.")
    logger.info("Existing voice profile will be replaced when enrollment completes.")

    with tempfile.TemporaryDirectory(prefix="secondvoice-enroll-") as temp_dir:
        audio_paths = []
        for index, prompt in enumerate(SPEAKER_ENROLLMENT_PROMPTS, start=1):
            print_enrollment_prompt(index, len(SPEAKER_ENROLLMENT_PROMPTS), prompt)
            input("Press ENTER, then read the sentence out loud.")

            audio_path = Path(temp_dir) / f"enrollment-{index:02d}.wav"
            capture_enrollment_utterance(
                audio_path,
                silence_seconds=SPEAKER_ENROLLMENT_SILENCE_SECONDS,
                silence_threshold=DEFAULT_SILENCE_THRESHOLD,
                max_record_seconds=SPEAKER_ENROLLMENT_MAX_SECONDS,
            )
            audio_paths.append(audio_path)

        identifier = SpeakerIdentifier(log_missing_profile=False)
        identifier.enroll_from_clips(audio_paths)

    logger.info("Saved interviewee voice embedding: {}", SPEAKER_PROFILE_EMBEDDING_PATH)
    logger.info("Saved interviewee voice metadata: {}", SPEAKER_PROFILE_METADATA_PATH)


def stream_loop(options: RuntimeOptions) -> None:
    """Continuously capture interview segments and submit each segment for feedback."""
    is_first_submission = True

    print_stream_mode_banner(options)

    with tempfile.TemporaryDirectory(prefix="secondvoice-eval-") as temp_dir:
        segment_queue: queue.Queue[Path | Exception] = queue.Queue()
        stop_event = threading.Event()
        recorder = start_stream_recorder(
            Path(temp_dir),
            segment_queue,
            stop_event,
        )
        photo_timer = start_photo_timer(stop_event) if options.upload_photo else None

        try:
            transcriber = LocalTranscriber(DEFAULT_TRANSCRIPTION_MODEL)
            speaker_identifier = SpeakerIdentifier()
            while True:
                audio_path = next_stream_segment(segment_queue)
                if audio_path is None:
                    continue

                submitted = process_stream_segment(
                    audio_path,
                    transcriber,
                    speaker_identifier,
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
            if photo_timer is not None:
                photo_timer.join()
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


def start_photo_timer(stop_event: threading.Event) -> threading.Thread:
    """Start a background timer that captures photos every configured interval."""
    photo_timer = threading.Thread(
        target=capture_photos_on_interval,
        args=(stop_event, PHOTO_CAPTURE_INTERVAL_SECONDS),
    )
    photo_timer.start()
    return photo_timer


def capture_photos_on_interval(
    stop_event: threading.Event,
    interval_seconds: float,
) -> None:
    """Capture photos at +interval, +2*interval, +3*interval until stopped."""
    next_capture_time = time.monotonic() + interval_seconds
    while True:
        wait_seconds = max(0.0, next_capture_time - time.monotonic())
        if stop_event.wait(wait_seconds):
            return

        try:
            photo_path = take_photo()
        except CameraCaptureError as error:
            logger.warning("Photo capture failed: {}", error)
        else:
            logger.info("Saved interview photo: {}", photo_path)

        next_capture_time += interval_seconds


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
    speaker_identifier: SpeakerIdentifier,
    options: RuntimeOptions,
    include_mode_prompt: bool,
) -> bool:
    """Transcribe one stream segment and optionally submit it for feedback."""
    speaker_hint = build_speaker_hint(audio_path, speaker_identifier)
    transcript = transcriber.transcribe(audio_path)
    audio_path.unlink(missing_ok=True)
    print_transcript(transcript)
    print_speaker_hint(speaker_hint)

    if not transcript:
        logger.info("No speech detected. Listening again.")
        return False

    if options.ask_chatgpt:
        photo_path = latest_interview_photo() if options.upload_photo else None
        submit_to_chatgpt(
            build_stream_prompt(
                transcript,
                include_mode_prompt,
                speaker_hint,
                include_photo_context=photo_path is not None,
            ),
            photo_path=photo_path,
            browser_mode=options.browser_mode,
        )
    logger.info("")
    return options.ask_chatgpt


def latest_interview_photo(photo_dir: Path = INTERVIEW_PHOTO_DIR) -> Path | None:
    """Return the newest non-empty image in the interview photo directory."""
    if not photo_dir.exists():
        logger.warning("No interview photo directory found at {}", photo_dir)
        return None

    photos = [
        path
        for path in photo_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in INTERVIEW_PHOTO_EXTENSIONS
        and path.stat().st_size > 0
    ]
    if not photos:
        logger.warning("No interview photos found in {}", photo_dir)
        return None

    return max(photos, key=lambda path: (path.stat().st_mtime_ns, path.name))


def build_speaker_hint(audio_path: Path, speaker_identifier: SpeakerIdentifier) -> SpeakerHint:
    """Return a speaker hint, falling back gracefully when matching is unavailable."""
    try:
        return speaker_identifier.match(audio_path)
    except RuntimeError as error:
        logger.warning("Voice matching unavailable: {}", error)
        return SpeakerHint(
            role_hint="unknown",
            confidence=None,
            similarity=None,
            profile_available=False,
        )


def build_stream_prompt(
    transcript: str,
    include_mode_prompt: bool,
    speaker_hint: SpeakerHint | None = None,
    include_photo_context: bool = False,
) -> str:
    """Return a prompt that asks ChatGPT to evaluate an interview transcript segment."""
    photo_context = f"\n{PHOTO_CONTEXT_PROMPT}\n" if include_photo_context else ""
    segment_prompt = (
        "Classify and process this transcript segment.\n\n"
        f"Local voice role hint: {speaker_hint_role(speaker_hint)}\n"
        f"Enrolled interviewee voice match confidence: {speaker_hint_value(speaker_hint)}\n"
        "Voice hint interpretation: higher means the audio is more likely the interviewee; "
        "lower means it is more likely the interviewer or unknown.\n"
        f"{photo_context}\n"
        f"Transcript:\n{transcript}"
    )
    if include_mode_prompt:
        return f"{STREAM_PROMPT}\n\n{segment_prompt}"

    return segment_prompt


def speaker_hint_value(speaker_hint: SpeakerHint | None) -> str:
    """Return the prompt confidence value for an optional speaker hint."""
    if speaker_hint is None:
        return "unavailable"
    return speaker_hint.prompt_value()


def speaker_hint_role(speaker_hint: SpeakerHint | None) -> str:
    """Return the prompt role hint for an optional speaker hint."""
    if speaker_hint is None or not speaker_hint.profile_available:
        return "unknown"
    return speaker_hint.role_hint


def print_enrollment_prompt(index: int, total: int, prompt: str) -> None:
    """Print one enrollment sentence cue."""
    logger.info("")
    logger.info("Enrollment sentence {}/{}", index, total)
    logger.info("Read this sentence: {}", prompt)


def print_speaker_hint(speaker_hint: SpeakerHint) -> None:
    """Print the voice match confidence for the most recent segment."""
    logger.info("Interviewee voice hint: {}", speaker_hint.log_value())


def print_stream_mode_banner(options: RuntimeOptions) -> None:
    """Print the active stream-mode trigger settings."""
    logger.info("Stream mode is active.")
    logger.info("Audio start trigger: speech begins")
    logger.info("Segment trigger: {:g}s of silence", STREAM_SILENCE_SECONDS)
    if options.upload_photo:
        logger.info(
            "Photo upload: enabled; using latest photo in {}",
            INTERVIEW_PHOTO_DIR,
        )
        logger.info(
            "Photo capture: every {:g}s after an initial {:g}s wait",
            PHOTO_CAPTURE_INTERVAL_SECONDS,
            PHOTO_CAPTURE_INTERVAL_SECONDS,
        )
    else:
        logger.info("Photo upload: disabled")
    logger.info("Recording continues while segments are transcribed")
    if options.ask_chatgpt:
        logger.info("ChatGPT submission: enabled")
        logger.info("Segment role detection: delegated to ChatGPT")
    else:
        logger.info("ChatGPT submission: disabled")
        logger.info("Echo output: transcript plus interviewee voice confidence")
    logger.info("Press Ctrl+C to stop.")


def print_transcript(transcript: str) -> None:
    """Print the transcript from the most recent captured utterance."""
    logger.info("Heard:\n{}", transcript.strip() or "(No speech detected.)")
