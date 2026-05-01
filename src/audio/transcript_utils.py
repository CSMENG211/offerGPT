from dataclasses import dataclass
import re


TRANSCRIPT_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


@dataclass(frozen=True)
class TranscriptWord:
    """Normalized transcript token plus its source span."""

    text: str
    start: int
    end: int


def normalize_transcript_words(transcript: str) -> list[str]:
    """Return lowercase word tokens for transcript comparison."""
    return [word.text for word in normalized_transcript_tokens(transcript)]


def normalized_transcript_tokens(transcript: str) -> list[TranscriptWord]:
    """Return lowercase word tokens with source spans."""
    return [
        TranscriptWord(match.group(0).lower(), match.start(), match.end())
        for match in TRANSCRIPT_WORD_PATTERN.finditer(transcript.lower())
    ]


def is_repetitive_transcript(transcript: str) -> bool:
    """Return whether a transcript looks like an ASR repetition loop."""
    words = normalize_transcript_words(transcript)
    return words_are_repetitive(words) or repetitive_suffix_start(words) is not None


def words_are_repetitive(words: list[str], min_tokens: int = 20) -> bool:
    """Return whether the full token sequence looks repetitive."""
    return repetitive_window_start_offset(words, min_tokens=min_tokens) is not None


def repetitive_window_start_offset(words: list[str], min_tokens: int = 20) -> int | None:
    """Return the start of the repeated pattern inside a repetitive window."""
    if len(words) < min_tokens:
        return None

    unique_ratio = len(set(words)) / len(words)
    if unique_ratio <= 0.25:
        return 0

    if len(words) >= 20 and unique_ratio <= 0.35:
        return 0

    if unique_ratio <= 0.35:
        return dominant_ngram_start(words, ngram_size=2, min_coverage=0.5)

    if unique_ratio <= 0.45:
        return dominant_ngram_start(words, ngram_size=3, min_coverage=0.5)

    return None


def repetitive_suffix_start(
    words: list[str],
    min_window_tokens: int = 12,
    min_prefix_tokens: int = 3,
) -> int | None:
    """Return the token index where a trailing repetition loop begins, if any."""
    if len(words) < min_window_tokens:
        return None

    for start in range(0, len(words) - min_window_tokens + 1):
        window = words[start : start + min_window_tokens]
        window_offset = repetitive_window_start_offset(
            window,
            min_tokens=min_window_tokens,
        )
        if window_offset is None:
            continue
        suffix_start = start + window_offset
        if suffix_start < min_prefix_tokens:
            return 0
        return suffix_start

    return None


def dominant_ngram_start(
    words: list[str],
    ngram_size: int,
    min_coverage: float,
) -> int | None:
    """Return the first index of the most repeated n-gram when coverage is high."""
    if len(words) < ngram_size:
        return None

    counts: dict[tuple[str, ...], int] = {}
    first_indexes: dict[tuple[str, ...], int] = {}
    for index in range(len(words) - ngram_size + 1):
        ngram = tuple(words[index : index + ngram_size])
        counts[ngram] = counts.get(ngram, 0) + 1
        first_indexes.setdefault(ngram, index)

    dominant_ngram, dominant_count = max(counts.items(), key=lambda item: item[1])
    if dominant_count * ngram_size / len(words) < min_coverage:
        return None

    return first_indexes[dominant_ngram]
