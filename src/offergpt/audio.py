import queue
import wave
from pathlib import Path

import sounddevice as sd


SAMPLE_RATE = 16_000
CHANNELS = 1


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
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        device=device,
        callback=callback,
    ):
        input()

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        while not audio_queue.empty():
            wav_file.writeframes(audio_queue.get())
