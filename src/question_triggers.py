import re
from typing import Literal

from constants import DEFAULT_QUESTION_START_PHRASES

QuestionTriggerMode = Literal["phrase", "smart", "always"]


def extract_question_prompt(
    transcript: str,
    start_phrases: list[str] | tuple[str, ...] = DEFAULT_QUESTION_START_PHRASES,
    mode: QuestionTriggerMode = "phrase",
) -> str | None:
    """Extract a prompt when the transcript matches the selected trigger mode."""
    if mode == "always":
        return transcript.strip()

    phrase_prompt = extract_after_question_start_phrase(transcript, start_phrases)
    if phrase_prompt is not None:
        return phrase_prompt

    if mode == "smart" and is_question(transcript):
        return transcript.strip(" .,:;-")

    return None


def extract_after_question_start_phrase(
    transcript: str,
    start_phrases: list[str] | tuple[str, ...],
) -> str | None:
    """Return transcript text that appears after a configured start phrase."""
    normalized_transcript = normalize(transcript)

    for phrase in start_phrases:
        normalized_phrase = normalize(phrase)
        match = re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_transcript)
        if match:
            prompt = transcript_after_normalized_index(transcript, normalized_transcript, match.end())
            return strip_leading_connector(prompt)

    return None


def is_question(transcript: str) -> bool:
    """Return whether a transcript appears to be a direct question."""
    return transcript.strip().endswith("?")


def normalize(text: str) -> str:
    """Lowercase text and collapse punctuation into single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def transcript_after_normalized_index(
    original: str,
    normalized_original: str,
    normalized_index: int,
) -> str:
    """Map a normalized text index back to the corresponding original-word suffix."""
    if normalized_index >= len(normalized_original):
        return ""

    normalized_suffix = normalized_original[normalized_index:].strip()
    if not normalized_suffix:
        return ""

    suffix_words = normalized_suffix.split()
    original_words = re.findall(r"\S+", original)

    if len(suffix_words) > len(original_words):
        return ""

    return " ".join(original_words[-len(suffix_words):]).strip(" .,:;-")


def strip_leading_connector(prompt: str) -> str:
    """Remove filler words that often connect a trigger phrase to the prompt."""
    cleaned = prompt
    while True:
        next_cleaned = re.sub(
            r"^(is that|is|that|with|about)\b[\s:,.;-]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        if next_cleaned == cleaned.strip():
            return next_cleaned
        cleaned = next_cleaned
