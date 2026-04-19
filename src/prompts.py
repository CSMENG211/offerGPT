from constants import STREAM_PROMPT
from speech import SpeakerHint

PHOTO_CONTEXT_PROMPT = (
    "Attached image context: the uploaded image is the current state of the "
    "problem board. Use it as visual context for the entire problem, and "
    "do not treat it as a separate question."
)


def build_stream_prompt(
    transcript: str,
    include_mode_prompt: bool,
    speaker_hint: SpeakerHint | None = None,
    include_photo_context: bool = False,
) -> str:
    """Return a prompt that asks ChatGPT to evaluate an interview transcript segment."""
    photo_context = f"\n{PHOTO_CONTEXT_PROMPT}\n" if include_photo_context else ""
    segment_prompt = (
        "Classify and process this transcript segment.\n\n"
        f"Local voice role hint: {speaker_hint_role(speaker_hint)}\n"
        f"Enrolled interviewee voice match confidence: {speaker_hint_value(speaker_hint)}\n"
        "Voice hint interpretation: higher means the audio is more likely the interviewee; "
        "lower means it is more likely the interviewer or unknown.\n"
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
