import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from camera import CameraCaptureError, take_photo
from constants import (
    LIVE_INTERVIEW_PHOTO_PATH,
    LIVE_PHOTO_CAPTURE_INITIAL_SECONDS,
    LIVE_PHOTO_CAPTURE_INTERVAL_SECONDS,
    TEST_INTERVIEW_PHOTO_PATH,
    TEST_PHOTO_CAPTURE_INITIAL_SECONDS,
    TEST_PHOTO_CAPTURE_INTERVAL_SECONDS,
)

PhotoMode = Literal["none", "test", "live"]
PhotoSignature = tuple[int, int]


@dataclass
class PhotoUploadTracker:
    """Track the last photo file version successfully submitted."""

    last_signature: PhotoSignature | None = None


def start_photo_timer(
    stop_event: threading.Event,
    photo_mode: PhotoMode,
) -> threading.Thread:
    """Start a background timer that captures photos every configured interval."""
    photo_path, initial_seconds, interval_seconds = photo_capture_settings(photo_mode)
    photo_timer = threading.Thread(
        target=capture_photos_on_interval,
        args=(
            stop_event,
            photo_path,
            initial_seconds,
            interval_seconds,
        ),
    )
    photo_timer.start()
    return photo_timer


def photo_capture_settings(photo_mode: PhotoMode) -> tuple[Path, float, float]:
    """Return the capture target, initial delay, and interval for a photo mode."""
    if photo_mode == "test":
        return (
            TEST_INTERVIEW_PHOTO_PATH,
            TEST_PHOTO_CAPTURE_INITIAL_SECONDS,
            TEST_PHOTO_CAPTURE_INTERVAL_SECONDS,
        )

    if photo_mode == "live":
        return (
            LIVE_INTERVIEW_PHOTO_PATH,
            LIVE_PHOTO_CAPTURE_INITIAL_SECONDS,
            LIVE_PHOTO_CAPTURE_INTERVAL_SECONDS,
        )

    raise ValueError(f"Photo mode {photo_mode!r} does not capture photos.")


def capture_photos_on_interval(
    stop_event: threading.Event,
    photo_path: Path,
    initial_seconds: float,
    interval_seconds: float,
) -> None:
    """Capture photos at +initial, then every interval until stopped."""
    next_capture_time = time.monotonic() + initial_seconds
    while True:
        wait_seconds = max(0.0, next_capture_time - time.monotonic())
        if stop_event.wait(wait_seconds):
            return

        try:
            saved_photo_path = take_photo(photo_path)
        except CameraCaptureError as error:
            logger.warning("Photo capture failed: {}", error)
        else:
            logger.info("Saved interview photo: {}", saved_photo_path)

        next_capture_time += interval_seconds


def next_photo_upload(
    photo_mode: PhotoMode,
    photo_tracker: PhotoUploadTracker,
) -> tuple[Path | None, PhotoSignature | None]:
    """Return a photo path only when the selected image changed since upload."""
    photo_path = interview_photo_path(photo_mode)
    if photo_path is None:
        return None, None

    photo_signature = current_photo_signature(photo_path)
    if photo_signature is None:
        logger.warning("Photo unavailable at {}; submitting text only.", photo_path)
        return None, None

    if photo_signature == photo_tracker.last_signature:
        logger.info("Photo unchanged since last upload; submitting text only.")
        return None, None

    return photo_path, photo_signature


def current_photo_signature(photo_path: Path) -> PhotoSignature | None:
    """Return the file identity used to decide whether a photo changed."""
    try:
        stat = photo_path.stat()
    except FileNotFoundError:
        return None

    if not photo_path.is_file() or stat.st_size == 0:
        return None

    return stat.st_mtime_ns, stat.st_size


def interview_photo_path(photo_mode: PhotoMode) -> Path | None:
    """Return the fixed photo path for the selected photo mode."""
    if photo_mode == "test":
        return TEST_INTERVIEW_PHOTO_PATH
    if photo_mode == "live":
        return LIVE_INTERVIEW_PHOTO_PATH
    return None
