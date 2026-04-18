from array import array
from collections.abc import Iterable
from collections import deque
import math
import queue
import threading
import wave
from pathlib import Path

from loguru import logger
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
            logger.warning("Audio warning: {}", status)
        audio_queue.put(bytes(indata))

    def write_audio(wav_file: wave.Wave_write) -> None:
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                break
            wav_file.writeframes(chunk)

    logger.info("Recording. Speak now, then press ENTER to stop.")
    with open_wav_writer(output_path) as wav_file:
        writer = threading.Thread(target=write_audio, args=(wav_file,))
        writer.start()

        try:
            with sd.RawInputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype="int16",
                callback=callback,
            ):
                input()
        finally:
            audio_queue.put(None)
            writer.join()


def capture_utterance(
    output_path: Path,
    silence_seconds: float = DEFAULT_SILENCE_SECONDS,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
    max_record_seconds: float | None = DEFAULT_MAX_RECORD_SECONDS,
) -> None:
    """Capture one utterance from the default microphone using silence detection."""
    blocksize = audio_blocksize()
    silence_blocks_needed = block_count_for_seconds(silence_seconds)
    max_blocks = optional_block_count_for_seconds(max_record_seconds)
    pre_roll = create_pre_roll_buffer()
    recorded_blocks = 0
    silent_blocks = 0
    recording_started = False

    logger.info("Audio start trigger: speech begins. Press Ctrl+C to stop.")
    with open_wav_writer(output_path) as wav_file:
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
                    logger.warning("Audio warning: input overflowed")

                is_speech = chunk_is_speech(chunk, silence_threshold)

                if not recording_started:
                    pre_roll.append(chunk)
                    if is_speech:
                        logger.info("Utterance started. Capturing audio...")
                        recording_started = True
                        write_chunks(wav_file, pre_roll)
                        recorded_blocks += len(pre_roll)
                        silent_blocks = 0
                    continue

                wav_file.writeframes(chunk)
                recorded_blocks += 1
                if is_speech:
                    silent_blocks = 0
                else:
                    silent_blocks += 1

                if silent_blocks >= silence_blocks_needed:
                    logger.info("Audio segment trigger: {:g}s of silence.", silence_seconds)
                    break

                if max_blocks is not None and recorded_blocks >= max_blocks:
                    logger.info("Max recording length reached ({:g}s).", max_record_seconds)
                    break


def stream_utterance_segments(
    output_dir: Path,
    segment_queue: queue.Queue[Path | Exception],
    stop_event: threading.Event,
    silence_seconds: float = DEFAULT_SILENCE_SECONDS,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
) -> None:
    """Continuously record voice-triggered utterance segments to WAV files."""
    blocksize = audio_blocksize()
    silence_blocks_needed = block_count_for_seconds(silence_seconds)
    pre_roll = create_pre_roll_buffer()
    silent_blocks = 0
    recording_started = False
    segment_index = 0
    wav_file: wave.Wave_write | None = None
    segment_path: Path | None = None

    def start_segment() -> wave.Wave_write:
        nonlocal segment_index, segment_path
        segment_index += 1
        segment_path = output_dir / f"stream-segment-{segment_index:04d}.wav"
        return open_wav_writer(segment_path)

    def finish_segment() -> None:
        nonlocal wav_file, segment_path
        if wav_file is None or segment_path is None:
            return
        wav_file.close()
        segment_queue.put(segment_path)
        wav_file = None
        segment_path = None

    logger.info("Audio stream active. Waiting for speech...")
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
                        logger.warning("Audio warning: input overflowed")

                    is_speech = chunk_is_speech(chunk, silence_threshold)

                    if not recording_started:
                        pre_roll.append(chunk)
                        if is_speech:
                            logger.info("Utterance started. Capturing audio...")
                            recording_started = True
                            wav_file = start_segment()
                            write_chunks(wav_file, pre_roll)
                            silent_blocks = 0
                        continue

                    if wav_file is not None:
                        wav_file.writeframes(chunk)

                    if is_speech:
                        silent_blocks = 0
                    else:
                        silent_blocks += 1

                    if silent_blocks >= silence_blocks_needed:
                        logger.info("Audio segment trigger: {:g}s of silence.", silence_seconds)
                        finish_segment()
                        recording_started = False
                        silent_blocks = 0
                        pre_roll.clear()
        except Exception as error:
            segment_queue.put(error)
    finally:
        if recording_started:
            finish_segment()


def open_wav_writer(output_path: Path) -> wave.Wave_write:
    """Open a mono int16 WAV file using the app's audio settings."""
    wav_file = wave.open(str(output_path), "wb")
    wav_file.setnchannels(AUDIO_CHANNELS)
    wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
    wav_file.setframerate(AUDIO_SAMPLE_RATE)
    return wav_file


def audio_blocksize() -> int:
    """Return the number of samples in one audio chunk."""
    return int(AUDIO_SAMPLE_RATE * AUDIO_CHUNK_SECONDS)


def block_count_for_seconds(seconds: float) -> int:
    """Return the number of audio chunks needed to cover a duration."""
    return max(1, math.ceil(seconds / AUDIO_CHUNK_SECONDS))


def optional_block_count_for_seconds(seconds: float | None) -> int | None:
    """Return a block count for a duration, preserving None as uncapped."""
    if seconds is None:
        return None
    return block_count_for_seconds(seconds)


def create_pre_roll_buffer() -> deque[bytes]:
    """Return a buffer that keeps audio from just before speech starts."""
    return deque(maxlen=block_count_for_seconds(AUDIO_PRE_ROLL_SECONDS))


def write_chunks(wav_file: wave.Wave_write, chunks: Iterable[bytes]) -> None:
    """Write a sequence of raw int16 audio chunks to a WAV file."""
    for chunk in chunks:
        wav_file.writeframes(chunk)


def chunk_is_speech(chunk: bytes, threshold: int) -> bool:
    """Return whether an audio chunk crosses the configured speech threshold."""
    return rms_level(chunk) >= threshold


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
