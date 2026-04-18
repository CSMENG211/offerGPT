from array import array
from collections import deque
import math
import queue
import threading
import wave
from pathlib import Path

import sounddevice as sd

from constants import (
    AUDIO_CHANNELS,
    AUDIO_CHUNK_SECONDS,
    AUDIO_PRE_ROLL_SECONDS,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH_BYTES,
    DEFAULT_MAX_RECORD_SECONDS,
    DEFAULT_SILENCE_SECONDS,
    DEFAULT_SILENCE_THRESHOLD,
)


def record_until_enter(output_path: Path) -> None:
    """Record from the default microphone until the user presses ENTER."""
    audio_queue: queue.Queue[bytes | None] = queue.Queue()

    def callback(indata, _frames, _time, status) -> None:
        if status:
            print(f"Audio warning: {status}")
        audio_queue.put(bytes(indata))

    def write_audio(wav_file: wave.Wave_write) -> None:
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                break
            wav_file.writeframes(chunk)

    print("Recording. Speak now, then press ENTER to stop.")
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        writer = threading.Thread(target=write_audio, args=(wav_file,))
        writer.start()

        with sd.RawInputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype="int16",
            callback=callback,
        ):
            input()

        audio_queue.put(None)
        writer.join()


def capture_utterance(
    output_path: Path,
    silence_seconds: float = DEFAULT_SILENCE_SECONDS,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
    max_record_seconds: float | None = DEFAULT_MAX_RECORD_SECONDS,
) -> None:
    """Capture one utterance from the default microphone using silence detection."""
    blocksize = int(AUDIO_SAMPLE_RATE * AUDIO_CHUNK_SECONDS)
    silence_blocks_needed = max(1, math.ceil(silence_seconds / AUDIO_CHUNK_SECONDS))
    max_blocks = (
        max(1, math.ceil(max_record_seconds / AUDIO_CHUNK_SECONDS))
        if max_record_seconds is not None
        else None
    )
    pre_roll = deque(maxlen=math.ceil(AUDIO_PRE_ROLL_SECONDS / AUDIO_CHUNK_SECONDS))
    recorded_blocks = 0
    silent_blocks = 0
    recording_started = False

    print("Audio start trigger: speech begins. Press Ctrl+C to stop.", flush=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)

        with sd.RawInputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype="int16",
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
                        for pre_roll_chunk in pre_roll:
                            wav_file.writeframes(pre_roll_chunk)
                            recorded_blocks += 1
                        silent_blocks = 0
                    continue

                wav_file.writeframes(chunk)
                recorded_blocks += 1
                if is_speech:
                    silent_blocks = 0
                else:
                    silent_blocks += 1

                if silent_blocks >= silence_blocks_needed:
                    print(
                        f"Audio segment trigger: {silence_seconds:g}s of silence.",
                        flush=True,
                    )
                    break

                if max_blocks is not None and recorded_blocks >= max_blocks:
                    print(
                        f"Max recording length reached ({max_record_seconds:g}s).",
                        flush=True,
                    )
                    break


def stream_utterance_segments(
    output_dir: Path,
    segment_queue: queue.Queue[Path | Exception],
    stop_event: threading.Event,
    silence_seconds: float = DEFAULT_SILENCE_SECONDS,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
) -> None:
    """Continuously record voice-triggered utterance segments to WAV files."""
    blocksize = int(AUDIO_SAMPLE_RATE * AUDIO_CHUNK_SECONDS)
    silence_blocks_needed = max(1, math.ceil(silence_seconds / AUDIO_CHUNK_SECONDS))
    pre_roll = deque(maxlen=math.ceil(AUDIO_PRE_ROLL_SECONDS / AUDIO_CHUNK_SECONDS))
    silent_blocks = 0
    recording_started = False
    segment_index = 0
    wav_file: wave.Wave_write | None = None
    segment_path: Path | None = None

    def start_segment() -> wave.Wave_write:
        nonlocal segment_index, segment_path
        segment_index += 1
        segment_path = output_dir / f"stream-segment-{segment_index:04d}.wav"
        output = wave.open(str(segment_path), "wb")
        output.setnchannels(AUDIO_CHANNELS)
        output.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        output.setframerate(AUDIO_SAMPLE_RATE)
        return output

    def finish_segment() -> None:
        nonlocal wav_file, segment_path
        if wav_file is None or segment_path is None:
            return
        wav_file.close()
        segment_queue.put(segment_path)
        wav_file = None
        segment_path = None

    print("Audio stream active. Waiting for speech...", flush=True)
    try:
        try:
            with sd.RawInputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype="int16",
                blocksize=blocksize,
            ) as stream:
                while not stop_event.is_set():
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
                            wav_file = start_segment()
                            for pre_roll_chunk in pre_roll:
                                wav_file.writeframes(pre_roll_chunk)
                            silent_blocks = 0
                        continue

                    if wav_file is not None:
                        wav_file.writeframes(chunk)

                    if is_speech:
                        silent_blocks = 0
                    else:
                        silent_blocks += 1

                    if silent_blocks >= silence_blocks_needed:
                        print(
                            f"Audio segment trigger: {silence_seconds:g}s of silence.",
                            flush=True,
                        )
                        finish_segment()
                        recording_started = False
                        silent_blocks = 0
                        pre_roll.clear()
        except Exception as error:
            segment_queue.put(error)
    finally:
        if recording_started:
            finish_segment()


def write_wav(output_path: Path, chunks: list[bytes]) -> None:
    """Write raw int16 audio chunks to a mono WAV file."""
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        for chunk in chunks:
            wav_file.writeframes(chunk)


def rms_level(chunk: bytes) -> float:
    """Calculate the root-mean-square amplitude for an int16 audio chunk."""
    if not chunk:
        return 0.0

    samples = array("h")
    samples.frombytes(chunk)
    if not samples:
        return 0.0

    square_sum = sum(sample * sample for sample in samples)
    return math.sqrt(square_sum / len(samples))
