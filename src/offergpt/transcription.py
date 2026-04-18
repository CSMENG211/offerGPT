from pathlib import Path

from offergpt.constants import DEFAULT_TRANSCRIPTION_MODEL

DEFAULT_MODEL = DEFAULT_TRANSCRIPTION_MODEL


class LocalTranscriber:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        from faster_whisper import WhisperModel

        print("Loading local Whisper model. The first run may download model files...", flush=True)
        self.model = WhisperModel(model, device="auto", compute_type="auto")
        print("Model loaded.", flush=True)

    def transcribe(self, audio_path: Path) -> str:
        print("Decoding audio...", flush=True)
        segments, _ = self.model.transcribe(str(audio_path), beam_size=5)

        transcript_parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                transcript_parts.append(text)
                print(f"Partial: {text}", flush=True)

        print("Done decoding audio.", flush=True)
        return " ".join(transcript_parts).strip()


def transcribe(audio_path: Path, model: str = DEFAULT_MODEL) -> str:
    return LocalTranscriber(model).transcribe(audio_path)
