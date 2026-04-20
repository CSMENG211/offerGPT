from gpt.constants import PHOTO_CONTEXT_PROMPT, STREAM_PROMPT
from speech import SpeakerHint


def build_stream_prompt(
    transcript: str,
    include_mode_prompt: bool,
    speaker_hint: SpeakerHint | None = None,
    include_photo_context: bool = False,
) -> str:
    """Return a prompt that asks ChatGPT to evaluate an interview transcript segment."""
    photo_context = f"\n{PHOTO_CONTEXT_PROMPT}\n" if include_photo_context else ""
    segment_prompt = (
        "Process this transcript segment using the private speaker-classification rules.\n\n"
        f"Local voice role hint: {speaker_hint_role(speaker_hint)}\n"
        f"Enrolled interviewee voice match confidence: {speaker_hint_value(speaker_hint)}\n"
        f"Raw voice cosine similarity: {speaker_hint_similarity(speaker_hint)}\n"
        f"{photo_context}\n"
        f"Transcript:\n{transcript}"
    )
    if include_mode_prompt:
        return f"{STREAM_PROMPT}\n\n{segment_prompt}"

    return segment_prompt


def speaker_hint_value(speaker_hint: SpeakerHint | None) -> str:
    """Return the prompt confidence value for an optional speaker hint."""
    if speaker_hint is None:
        return "unavailable"
    return speaker_hint.prompt_value()


def speaker_hint_role(speaker_hint: SpeakerHint | None) -> str:
    """Return the prompt role hint for an optional speaker hint."""
    if speaker_hint is None or not speaker_hint.profile_available:
        return "unknown"
    return speaker_hint.role_hint


def speaker_hint_similarity(speaker_hint: SpeakerHint | None) -> str:
    """Return the raw cosine similarity for an optional speaker hint."""
    if speaker_hint is None or speaker_hint.similarity is None:
        return "unavailable"
    return f"{speaker_hint.similarity:.3f}"
