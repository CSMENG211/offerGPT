from pathlib import Path


AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH_BYTES = 2
AUDIO_CHUNK_SECONDS = 0.1
AUDIO_PRE_ROLL_SECONDS = 0.3

STREAM_SILENCE_SECONDS = 5.0
DEFAULT_SILENCE_THRESHOLD = 500

DEFAULT_TRANSCRIPTION_MODEL = "small"

CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_BROWSER_PROFILE = Path.home() / ".secondvoice" / "browser-profile"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
PERSISTENT_TYPE_DELAY_MS = 25

SPEAKER_PROFILE_DIR = Path.home() / ".secondvoice"
SPEAKER_PROFILE_METADATA_PATH = SPEAKER_PROFILE_DIR / "interviewee-voice-profile.json"
SPEAKER_PROFILE_EMBEDDING_PATH = SPEAKER_PROFILE_DIR / "interviewee-voice-embedding.pt"
SPEAKER_MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
SPEAKER_MODEL_DIR = SPEAKER_PROFILE_DIR / "speaker-model"
SPEAKER_MATCH_THRESHOLD = 0.65
SPEAKER_ENROLLMENT_SILENCE_SECONDS = 1.5
SPEAKER_ENROLLMENT_MAX_SECONDS = 10.0
SPEAKER_ENROLLMENT_PROMPTS = [
    "I would start by clarifying the input constraints and expected output.",
    "My first approach is brute force, then I would optimize using a hash map.",
    "The time complexity is O of n, and the space complexity is O of n.",
    "Could I confirm whether the array contains negative numbers or duplicates?",
    "I am thinking through the edge cases before finalizing the algorithm.",
    "If the input is empty, I would return early and avoid unnecessary work.",
    "Let me walk through a small example to verify the logic.",
    "I would test the happy path, boundary cases, and failure cases.",
    "For the system design, I would first clarify the scale, users, and latency requirements.",
    "The main components are an API gateway, application servers, a database, and a cache.",
    "We can use a load balancer to distribute traffic across multiple stateless services.",
    "For high read traffic, I would add caching with Redis and define cache invalidation.",
    "If we need durability and ordering, I would consider a message queue or event log.",
    "The database choice depends on query patterns, consistency needs, and write volume.",
    "For horizontal scaling, I would partition the data and avoid hot keys where possible.",
    "I would monitor latency, error rate, throughput, and saturation for each critical service.",
    "To improve reliability, I would add retries with backoff, timeouts, and idempotency keys.",
    "For consistency, I would clarify whether the product needs strong or eventual consistency.",
    "Security-wise, I would include authentication, authorization, rate limiting, and audit logging.",
    "Let me summarize the tradeoffs before choosing the final design.",
]

STREAM_PROMPT = (
    "You are SecondVoice, a mock interview evaluator. For each transcript "
    "segment, first classify whether the text is from the interviewer or "
    "the interviewee. You may receive an enrolled interviewee voice match "
    "confidence from 0.0 to 1.0. Use it only as a hint: higher values suggest "
    "the segment sounds like the enrolled interviewee, while lower values "
    "suggest the segment may be the interviewer or unknown. Prefer the "
    "transcript and accumulated context when they strongly disagree with the "
    "audio hint. If it is from the interviewer, treat it as problem "
    "context for the rest of the mock interview and briefly acknowledge the "
    "updated context without evaluating it. If it is from the interviewee, "
    "use the accumulated interviewer context to write the ideal concise "
    "answer, then evaluate the interviewee's response against that ideal. "
    "Focus on clarity, structure, technical correctness, missed signals, "
    "and one or two concrete ways to improve the answer. Give a short "
    "example phrasing that would make the feedback more actionable. If the "
    "speaker role is ambiguous, say so briefly, make the best reasonable "
    "classification from the text, and continue. Do not invent problem "
    "facts beyond the accumulated transcript context."
)
