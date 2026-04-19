#!/usr/bin/env python3
"""Capture a still photo from the built-in macOS camera.

This module can be imported and used from other code, or run directly:

    python src/camera_photo.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from constants import INTERVIEW_PHOTO_DIR


DEFAULT_CAMERA_NAME = "FaceTime HD Camera"
DEFAULT_OUTPUT_DIR = INTERVIEW_PHOTO_DIR


class CameraCaptureError(RuntimeError):
    """Raised when the camera photo cannot be captured."""


def take_photo(
    output_path: str | Path | None = None,
    *,
    camera_name: str = DEFAULT_CAMERA_NAME,
) -> Path:
    """Capture one photo with ``imagesnap`` and return the saved path.

    ``imagesnap`` is used because it is small, fast, and can target the built-in
    MacBook camera by name. OpenCV is intentionally avoided because macOS camera
    indices can point at Continuity Camera devices such as an iPhone or iPad.

    Photos are always written to ``/Users/flora/interview``. If ``output_path``
    is provided, only its filename is used.
    """

    if not shutil.which("imagesnap"):
        raise CameraCaptureError(
            "imagesnap is required to capture a named macOS camera.\n\n"
            "Install it with:\n"
            "  brew install imagesnap"
        )

    path = _resolve_output_path(output_path)
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


def _resolve_output_path(output_path: str | Path | None) -> Path:
    if output_path:
        filename = Path(output_path).name
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"camera-photo-{timestamp}.jpg"

    return DEFAULT_OUTPUT_DIR / filename


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Take one photo from the built-in macOS camera."
    )
    parser.add_argument(
        "output",
        nargs="?",
        help=(
            "Output filename. Directory components are ignored. "
            "Default: camera-photo-YYYYmmdd-HHMMSS.jpg"
        ),
    )
    parser.add_argument(
        "--camera-name",
        default=DEFAULT_CAMERA_NAME,
        help=f"Camera device name. Default: {DEFAULT_CAMERA_NAME!r}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        path = take_photo(args.output, camera_name=args.camera_name)
    except CameraCaptureError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Saved photo to {path}")


if __name__ == "__main__":
    main()
