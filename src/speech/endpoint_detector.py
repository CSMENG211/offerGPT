import json
import re
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from loguru import logger

from audio import SemanticEndpointResult, is_repetitive_transcript
from speech.constants import (
    DEFAULT_ENDPOINT_MODEL,
    ENDPOINT_LABEL_COMPLETE,
    ENDPOINT_LABEL_INCOMPLETE,
    ENDPOINT_SYSTEM_PROMPT,
    GIBBERISH_LABEL_GIBBERISH,
    GIBBERISH_LABEL_MEANINGFUL,
    GIBBERISH_SYSTEM_PROMPT,
    OLLAMA_CHAT_URL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
)
from speech.transcription import Transcriber


class OllamaSemanticEndpointDetector:
    """Draft-audio endpoint detector backed by local transcription and Ollama."""

    def __init__(self, model: str = DEFAULT_ENDPOINT_MODEL) -> None:
        self.model = model
        self._transcriber: Transcriber | None = None
        self._lock = threading.Lock()

    def set_transcriber(self, transcriber: Transcriber) -> None:
        """Attach the shared transcriber once Whisper has loaded."""
        with self._lock:
            self._transcriber = transcriber

    def is_complete(self, audio_path: Path) -> bool:
        """Return True only when the draft audio is confidently complete."""
        return self.detect(audio_path).is_complete

    def detect(self, audio_path: Path) -> SemanticEndpointResult:
        """Return the draft transcript and whether it is confidently complete."""
        transcriber = self._current_transcriber()
        if transcriber is None:
            logger.debug("Semantic endpoint check skipped; transcriber is not ready.")
            return SemanticEndpointResult(is_complete=False)

        transcript = transcriber.transcribe(audio_path, log_progress=False)
        if not transcript:
            logger.debug("Semantic endpoint check skipped; draft transcript is empty.")
            return SemanticEndpointResult(is_complete=False)

        if is_repetitive_transcript(transcript):
            logger.debug(
                "Semantic endpoint transcript ignored as repetitive: {}",
                transcript,
            )
            return SemanticEndpointResult(
                is_complete=False,
                transcript=transcript,
                is_gibberish=True,
            )

        is_gibberish = False
        try:
            gibberish_label, gibberish_duration_ms = classify_gibberish_transcript(
                transcript,
                self.model,
            )
            is_gibberish = gibberish_label == GIBBERISH_LABEL_GIBBERISH
        except URLError as error:
            logger.warning("Gibberish check could not reach Ollama: {}", error)
        except Exception as error:
            logger.warning("Gibberish check failed: {}", error)

        if is_gibberish:
            logger.debug(
                "Gibberish check: {} ({:.1f} ms) for draft: {}",
                gibberish_label,
                gibberish_duration_ms,
                transcript,
            )
            return SemanticEndpointResult(
                is_complete=False,
                transcript=transcript,
                is_gibberish=True,
            )

        try:
            label, duration_ms = classify_endpoint_transcript(transcript, self.model)
        except URLError as error:
            logger.warning("Semantic endpoint check could not reach Ollama: {}", error)
            return SemanticEndpointResult(is_complete=False, transcript=transcript)
        except Exception as error:
            logger.warning("Semantic endpoint check failed: {}", error)
            return SemanticEndpointResult(is_complete=False, transcript=transcript)

        logger.debug(
            "Semantic endpoint check: {} ({:.1f} ms) for draft: {}",
            label,
            duration_ms,
            transcript,
        )
        return SemanticEndpointResult(
            is_complete=label == ENDPOINT_LABEL_COMPLETE,
            transcript=transcript,
            is_gibberish=False,
        )

    def _current_transcriber(self) -> Transcriber | None:
        with self._lock:
            return self._transcriber


def classify_endpoint_transcript(
    transcript: str,
    model: str = DEFAULT_ENDPOINT_MODEL,
    url: str = OLLAMA_CHAT_URL,
    timeout_seconds: float = OLLAMA_REQUEST_TIMEOUT_SECONDS,
) -> tuple[str, float]:
    """Classify a transcript as COMPLETE or INCOMPLETE using Ollama."""
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0,
            "num_predict": 3,
        },
        "messages": [
            {"role": "system", "content": ENDPOINT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript: {transcript}"},
        ],
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    with urlopen(request, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    duration_ms = (time.perf_counter() - started) * 1000

    content = body["message"]["content"].strip().upper()
    if ENDPOINT_LABEL_INCOMPLETE in content:
        return ENDPOINT_LABEL_INCOMPLETE, duration_ms
    if ENDPOINT_LABEL_COMPLETE in content:
        return ENDPOINT_LABEL_COMPLETE, duration_ms
    return f"OTHER:{content}", duration_ms


def classify_gibberish_transcript(
    transcript: str,
    model: str = DEFAULT_ENDPOINT_MODEL,
    url: str = OLLAMA_CHAT_URL,
    timeout_seconds: float = OLLAMA_REQUEST_TIMEOUT_SECONDS,
) -> tuple[str, float]:
    """Classify a transcript as MEANINGFUL or GIBBERISH using Ollama."""
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0,
            "num_predict": 3,
        },
        "messages": [
            {"role": "system", "content": GIBBERISH_SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript: {transcript}"},
        ],
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    with urlopen(request, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    duration_ms = (time.perf_counter() - started) * 1000

    return parse_gibberish_label(body["message"]["content"]), duration_ms


def parse_gibberish_label(content: str) -> str:
    """Return a normalized gibberish label from an Ollama response."""
    normalized_content = content.strip().upper()
    labels = re.findall(r"[A-Z]+", normalized_content)
    if labels == [GIBBERISH_LABEL_GIBBERISH]:
        return GIBBERISH_LABEL_GIBBERISH
    if labels == [GIBBERISH_LABEL_MEANINGFUL]:
        return GIBBERISH_LABEL_MEANINGFUL
    return f"OTHER:{normalized_content}"
