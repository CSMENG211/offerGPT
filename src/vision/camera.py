#!/usr/bin/env python3
"""Capture a still photo from the built-in macOS camera."""

import shutil
import subprocess
from pathlib import Path

from vision.constants import DEFAULT_CAMERA_NAME, LIVE_INTERVIEW_PHOTO_PATH


class CameraCaptureError(RuntimeError):
    """Raised when the camera photo cannot be captured."""


def take_photo(
    output_path: Path = LIVE_INTERVIEW_PHOTO_PATH,
    *,
    camera_name: str = DEFAULT_CAMERA_NAME,
) -> Path:
    """Capture one photo with ``imagesnap`` and return the saved path.

    ``imagesnap`` is used because it is small, fast, and can target the built-in
    MacBook camera by name. OpenCV is intentionally avoided because macOS camera
    indices can point at Continuity Camera devices such as an iPhone or iPad.

    Photos are written to ``output_path``, replacing any existing image there.
    The default path is ``/Users/flora/interview/live.jpg``.
    """

    if not shutil.which("imagesnap"):
        raise CameraCaptureError(
            "imagesnap is required to capture a named macOS camera.\n\n"
            "Install it with:\n"
            "  brew install imagesnap"
        )

    path = output_path
    path.parent.mkdir(parents=True, exist_ok=True)

    command = ["imagesnap", "-d", camera_name, str(path)]
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise CameraCaptureError(
            f"imagesnap failed to capture from {camera_name!r}: {output}"
        )

    if not path.exists() or path.stat().st_size == 0:
        raise CameraCaptureError(f"imagesnap did not create a photo at {path}.")

    return path
