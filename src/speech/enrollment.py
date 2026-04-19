import tempfile
from pathlib import Path

from loguru import logger

from audio import capture_enrollment_utterance
from audio.constants import DEFAULT_SILENCE_THRESHOLD
from speech.constants import (
    SPEAKER_ENROLLMENT_MAX_SECONDS,
    SPEAKER_ENROLLMENT_PROMPTS,
    SPEAKER_ENROLLMENT_SILENCE_SECONDS,
    SPEAKER_PROFILE_EMBEDDING_PATH,
    SPEAKER_PROFILE_METADATA_PATH,
)
from speech.speaker_id import SpeakerIdentifier


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


def print_enrollment_prompt(index: int, total: int, prompt: str) -> None:
    """Print one enrollment sentence cue."""
    logger.info("")
    logger.info("Enrollment sentence {}/{}", index, total)
    logger.info("Read this sentence: {}", prompt)
