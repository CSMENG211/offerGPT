from pathlib import Path
from typing import Literal


AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH_BYTES = 2
AUDIO_CHUNK_SECONDS = 0.1
AUDIO_PRE_ROLL_SECONDS = 0.3

DEFAULT_SILENCE_SECONDS = 5.0
DEFAULT_SILENCE_THRESHOLD = 500
DEFAULT_MAX_RECORD_SECONDS = 120.0

DEFAULT_TRANSCRIPTION_MODEL = "small"
DEFAULT_QUESTION_TRIGGER_MODE = "smart"
DEFAULT_ANSWER_MODE = "helpful"

CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_BROWSER_PROFILE = Path.home() / ".secondvoice" / "browser-profile"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
PERSISTENT_TYPE_DELAY_MS = 25

DEFAULT_QUESTION_START_PHRASES = ("ok so the issue", "so the problem")

AnswerMode = Literal["generic", "helpful"]

ANSWER_MODE_PROMPTS: dict[AnswerMode, str] = {
    "generic": (
        "You are SecondVoice, a voice-triggered GPT answer assistant. "
        "For every user question in this chat, give a brief read-aloud answer "
        "that is safe, neutral, and non-committal. Do not invent dates, numbers, "
        "ownership, promises, or guarantees. Keep the answer concise and directly "
        "usable in a workplace conversation."
    ),
    "helpful": (
        "You are SecondVoice, a voice-triggered GPT answer assistant. "
        "For every user question in this chat, give a concise but highly useful "
        "read-aloud answer. Prefer clear structure, practical reasoning, and "
        "interview-quality phrasing. Keep it brief, direct, and easy to say out loud."
    ),
}
