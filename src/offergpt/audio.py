from array import array
from collections import deque
import math
import queue
import wave
from pathlib import Path

import sounddevice as sd

from offergpt.constants import (
    AUDIO_CHANNELS,
    AUDIO_CHUNK_SECONDS,
    AUDIO_PRE_ROLL_SECONDS,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH_BYTES,
    DEFAULT_MAX_RECORD_SECONDS,
    DEFAULT_SILENCE_SECONDS,
    DEFAULT_SILENCE_THRESHOLD,
)


def list_microphones() -> None:
    print("Input devices:")
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            default_marker = " (default)" if index == sd.default.device[0] else ""
            print(f"{index}: {device['name']}{default_marker}")


def record_until_enter(output_path: Path, device: int | None) -> None:
    audio_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time, status) -> None:
        if status:
            print(f"Audio warning: {status}")
        audio_queue.put(bytes(indata))

    print("Recording. Speak now, then press ENTER to stop.")
    with sd.RawInputStream(
        samplerate=AUDIO_SAMPLE_RATE,
        channels=AUDIO_CHANNELS,
        dtype="int16",
        device=device,
        callback=callback,
    ):
        input()

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        while not audio_queue.empty():
            wav_file.writeframes(audio_queue.get())


def capture_utterance(
    output_path: Path,
    device: int | None,
    silence_seconds: float = DEFAULT_SILENCE_SECONDS,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
    max_record_seconds: float = DEFAULT_MAX_RECORD_SECONDS,
) -> None:
    blocksize = int(AUDIO_SAMPLE_RATE * AUDIO_CHUNK_SECONDS)
    silence_blocks_needed = max(1, math.ceil(silence_seconds / AUDIO_CHUNK_SECONDS))
    max_blocks = max(1, math.ceil(max_record_seconds / AUDIO_CHUNK_SECONDS))
    pre_roll = deque(maxlen=math.ceil(AUDIO_PRE_ROLL_SECONDS / AUDIO_CHUNK_SECONDS))
    recorded_chunks = []
    silent_blocks = 0
    recording_started = False

    print("Audio start trigger: speech begins. Press Ctrl+C to stop.", flush=True)
    with sd.RawInputStream(
        samplerate=AUDIO_SAMPLE_RATE,
        channels=AUDIO_CHANNELS,
        dtype="int16",
        device=device,
        blocksize=blocksize,
    ) as stream:
        while True:
            data, overflowed = stream.read(blocksize)
            chunk = bytes(data)
            if overflowed:
                print("Audio warning: input overflowed")

            level = rms_level(chunk)
            is_speech = level >= silence_threshold

            if not recording_started:
                pre_roll.append(chunk)
                if is_speech:
                    print("Utterance started. Capturing audio...", flush=True)
                    recording_started = True
                    recorded_chunks.extend(pre_roll)
                    silent_blocks = 0
                continue

            recorded_chunks.append(chunk)
            if is_speech:
                silent_blocks = 0
            else:
                silent_blocks += 1

            if silent_blocks >= silence_blocks_needed:
                print(f"Audio stop trigger: {silence_seconds:g}s of silence.", flush=True)
                break

            if len(recorded_chunks) >= max_blocks:
                print(f"Max recording length reached ({max_record_seconds:g}s).", flush=True)
                break

    write_wav(output_path, recorded_chunks)


def write_wav(output_path: Path, chunks: list[bytes]) -> None:
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        for chunk in chunks:
            wav_file.writeframes(chunk)


def rms_level(chunk: bytes) -> float:
    if not chunk:
        return 0.0

    samples = array("h")
    samples.frombytes(chunk)
    if not samples:
        return 0.0

    square_sum = sum(sample * sample for sample in samples)
    return math.sqrt(square_sum / len(samples))
