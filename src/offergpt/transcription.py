from pathlib import Path


DEFAULT_MODEL = "small"


def transcribe(audio_path: Path, model: str = DEFAULT_MODEL) -> str:
    from faster_whisper import WhisperModel

    print("Loading local Whisper model. The first run may download model files...", flush=True)
    whisper_model = WhisperModel(model, device="auto", compute_type="auto")
    print("Model loaded. Decoding audio...", flush=True)
    segments, _ = whisper_model.transcribe(str(audio_path), beam_size=5)

    transcript_parts = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            transcript_parts.append(text)
            print(f"Partial: {text}", flush=True)

    print("Done decoding audio.", flush=True)
    return " ".join(transcript_parts).strip()
