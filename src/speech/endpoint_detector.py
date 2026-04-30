import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from loguru import logger

from audio import SemanticEndpointResult, trim_repetitive_transcript_suffix
from speech.constants import (
    DEFAULT_ENDPOINT_MODEL,
    ENDPOINT_LABEL_COMPLETE,
    ENDPOINT_LABEL_INCOMPLETE,
    ENDPOINT_SYSTEM_PROMPT,
    OLLAMA_CHAT_URL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
)


class OllamaSemanticEndpointDetector:
    """Semantic endpoint detector backed by local Ollama classification."""

    def __init__(self, model: str = DEFAULT_ENDPOINT_MODEL) -> None:
        self.model = model

    def classify_transcript(self, transcript: str) -> SemanticEndpointResult:
        """Return whether a transcript is semantically complete."""
        if not transcript:
            logger.debug("Semantic endpoint check skipped; draft transcript is empty.")
            return SemanticEndpointResult(is_complete=False)

        trimmed_transcript = trim_repetitive_transcript_suffix(transcript)
        if not trimmed_transcript:
            logger.debug(
                "Semantic endpoint transcript ignored as repetitive: {}",
                transcript,
            )
            return SemanticEndpointResult(
                is_complete=False,
                transcript=transcript,
                is_rejected=True,
            )
        if trimmed_transcript != transcript:
            logger.debug(
                "Semantic endpoint transcript trimmed from {!r} to {!r}.",
                transcript,
                trimmed_transcript,
            )
            transcript = trimmed_transcript

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
            is_rejected=False,
        )


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
