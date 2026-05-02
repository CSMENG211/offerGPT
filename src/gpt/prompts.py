from gpt.constants import PHOTO_CONTEXT_PROMPT, STREAM_PROMPT


def build_stream_prompt(
    transcript: str,
    include_mode_prompt: bool,
    include_photo_context: bool = False,
) -> str:
    """Return a prompt that asks ChatGPT to evaluate an interview transcript segment."""
    photo_context = f"\n{PHOTO_CONTEXT_PROMPT}\n" if include_photo_context else ""
    segment_prompt = (
        "Process this transcript segment.\n\n"
        f"{photo_context}\n"
        f"Transcript:\n{transcript}"
    )
    if include_mode_prompt:
        return f"{STREAM_PROMPT}\n\n{segment_prompt}"

    return segment_prompt
