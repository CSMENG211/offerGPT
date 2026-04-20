from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import queue
import re
import threading
import wave

from loguru import logger
import sounddevice as sd

from audio.levels import (
    audio_blocksize,
    block_count_for_seconds,
    create_pre_roll_buffer,
    rms_level,
)
from audio.wav import open_wav_writer, write_wav_file
from audio.constants import (
    AUDIO_CHANNELS,
    AUDIO_CHUNK_SECONDS,
    AUDIO_SAMPLE_RATE,
    DEFAULT_SILENCE_THRESHOLD,
    STREAM_FALLBACK_NEW_WORD_THRESHOLD,
    STREAM_HARD_SILENCE_SECONDS,
    STREAM_SEMANTIC_SILENCE_SECONDS,
    STREAM_SPEECH_CONTINUE_THRESHOLD_RATIO,
    STREAM_SPEECH_HANGOVER_SECONDS,
)

SemanticEndpointDetector = Callable[[Path], "SemanticEndpointResult"]


@dataclass(frozen=True)
class CompletedStreamSegment:
    """Recorded stream segment plus the trigger that ended it."""

    path: Path
    completion_reason: str


@dataclass(frozen=True)
class SemanticEndpointJob:
    """Snapshot of an in-progress segment to classify off the recorder thread."""

    segment_index: int
    pause_index: int
    chunks: list[bytes]


@dataclass(frozen=True)
class SemanticEndpointResult:
    """Semantic completion result for one queued draft segment snapshot."""

    is_complete: bool
    transcript: str = ""
    is_gibberish: bool = False
    segment_index: int = -1
    pause_index: int = -1


class StreamSpeechDetector:
    """Speech activity detector with separate start/continue thresholds."""

    def __init__(
        self,
        start_threshold: int,
        continue_threshold_ratio: float = STREAM_SPEECH_CONTINUE_THRESHOLD_RATIO,
        hangover_seconds: float = STREAM_SPEECH_HANGOVER_SECONDS,
    ) -> None:
        self.start_threshold = start_threshold
        self.continue_threshold = start_threshold * continue_threshold_ratio
        self.hangover_blocks = block_count_for_seconds(hangover_seconds)
        self.hangover_blocks_left = 0
        self.speech_started = False

    def is_speech(self, chunk: bytes) -> bool:
        """Return whether the chunk should count as speech for stream segmentation."""
        level = rms_level(chunk)
        if not self.speech_started:
            if level >= self.start_threshold:
                self.mark_speech()
                return True
            return False

        if level >= self.continue_threshold:
            self.mark_speech()
            return True

        if self.hangover_blocks_left > 0:
            self.hangover_blocks_left -= 1
            return True

        return False

    def mark_speech(self) -> None:
        """Record speech activity and refresh hangover protection."""
        self.speech_started = True
        self.hangover_blocks_left = self.hangover_blocks

    def reset(self) -> None:
        """Reset detector state for a new segment."""
        self.hangover_blocks_left = 0
        self.speech_started = False


class StreamSegmenter:
    """Continuously record voice-triggered utterance segments to WAV files."""

    def __init__(
        self,
        output_dir: Path,
        segment_queue: queue.Queue[CompletedStreamSegment | Exception],
        stop_event: threading.Event,
        hard_silence_seconds: float = STREAM_HARD_SILENCE_SECONDS,
        silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
        semantic_silence_seconds: float = STREAM_SEMANTIC_SILENCE_SECONDS,
        semantic_endpoint_detector: SemanticEndpointDetector | None = None,
        fallback_new_word_threshold: int = STREAM_FALLBACK_NEW_WORD_THRESHOLD,
    ) -> None:
        self.output_dir = output_dir
        self.segment_queue = segment_queue
        self.stop_event = stop_event
        self.hard_silence_seconds = hard_silence_seconds
        self.silence_threshold = silence_threshold
        self.semantic_silence_seconds = semantic_silence_seconds
        self.semantic_endpoint_detector = semantic_endpoint_detector
        self.fallback_new_word_threshold = fallback_new_word_threshold
        self.speech_detector = StreamSpeechDetector(silence_threshold)

        self.blocksize = audio_blocksize()
        self.hard_silence_blocks_needed = block_count_for_seconds(hard_silence_seconds)
        self.semantic_silence_blocks_needed = block_count_for_seconds(
            semantic_silence_seconds
        )
        self.pre_roll = create_pre_roll_buffer()
        self.recorded_chunks: list[bytes] = []
        self.segment_chunks = 0
        self.silent_blocks = 0
        self.semantic_check_queued_this_pause = False
        self.semantic_pause_index = 0
        self.recording_started = False
        self.segment_index = 0
        self.wav_file: wave.Wave_write | None = None
        self.segment_path: Path | None = None
        self.pending_completion_reason = "shutdown"
        self.latest_semantic_transcript = ""

        self.semantic_job_queue: queue.Queue[SemanticEndpointJob | None] | None = None
        self.semantic_result_queue: queue.Queue[SemanticEndpointResult] | None = None
        self.semantic_worker: threading.Thread | None = None

    def run(self) -> None:
        """Run the recorder loop until stopped, queueing completed segments."""
        self.start_semantic_worker()
        logger.info("Audio stream active. Waiting for audio input...")
        try:
            try:
                self.run_audio_stream()
            except Exception as error:
                self.segment_queue.put(error)
        finally:
            self.finish_active_segment()
            self.stop_semantic_worker()

    def start_semantic_worker(self) -> None:
        """Start the semantic endpoint worker when a detector is configured."""
        if self.semantic_endpoint_detector is None:
            return

        self.semantic_job_queue = queue.Queue()
        self.semantic_result_queue = queue.Queue()
        self.semantic_worker = threading.Thread(
            target=run_semantic_endpoint_worker,
            args=(
                self.output_dir,
                self.semantic_job_queue,
                self.semantic_result_queue,
                self.semantic_endpoint_detector,
            ),
        )
        self.semantic_worker.start()

    def stop_semantic_worker(self) -> None:
        """Stop the semantic endpoint worker if it was started."""
        if self.semantic_job_queue is not None:
            self.semantic_job_queue.put(None)
        if self.semantic_worker is not None:
            self.semantic_worker.join()

    def run_audio_stream(self) -> None:
        """Read microphone chunks and update the segment state machine."""
        with sd.RawInputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype="int16",
            blocksize=self.blocksize,
        ) as stream:
            while not self.stop_event.is_set():
                data, overflowed = stream.read(self.blocksize)
                chunk = bytes(data)
                if overflowed:
                    logger.warning("Audio warning: input overflowed")

                self.handle_audio_chunk(chunk)

    def handle_audio_chunk(self, chunk: bytes) -> None:
        """Process one raw audio chunk."""
        is_speech = self.speech_detector.is_speech(chunk)

        if not self.recording_started:
            self.pre_roll.append(chunk)
            if is_speech:
                self.start_segment()
            return

        self.write_segment_chunks([chunk])
        self.update_silence_state(is_speech)

        if self.handle_semantic_endpoint_results():
            return

        if self.should_queue_semantic_check():
            self.semantic_check_queued_this_pause = True
            self.queue_semantic_endpoint_check()

        if self.silent_blocks >= self.hard_silence_blocks_needed:
            self.handle_hard_silence_fallback()

    def start_segment(self) -> None:
        """Start writing a new stream segment."""
        logger.info("Audio input detected. Listening...")
        self.segment_index += 1
        self.segment_path = self.output_dir / f"stream-segment-{self.segment_index:04d}.wav"
        self.wav_file = open_wav_writer(self.segment_path)
        self.recording_started = True
        self.write_segment_chunks(self.pre_roll)
        self.segment_chunks = len(self.pre_roll)
        self.silent_blocks = 0
        self.semantic_check_queued_this_pause = False
        self.speech_detector.mark_speech()

    def finish_active_segment(self) -> None:
        """Queue the active segment during shutdown, if any."""
        if self.recording_started:
            self.finish_segment()

    def finish_segment_and_reset(self) -> None:
        """Finish the current segment and reset recorder state."""
        self.finish_segment()
        self.recording_started = False
        self.silent_blocks = 0
        self.semantic_check_queued_this_pause = False
        self.pre_roll.clear()
        self.speech_detector.reset()
        logger.info("Waiting for audio input...")

    def finish_segment(self) -> None:
        """Close and queue the current segment path."""
        if self.wav_file is None or self.segment_path is None:
            return

        self.wav_file.close()
        self.segment_queue.put(
            CompletedStreamSegment(
                path=self.segment_path,
                completion_reason=self.pending_completion_reason,
            )
        )
        self.wav_file = None
        self.segment_path = None
        self.recorded_chunks = []
        self.segment_chunks = 0
        self.pending_completion_reason = "shutdown"
        self.latest_semantic_transcript = ""

    def write_segment_chunks(self, chunks: Iterable[bytes]) -> None:
        """Write raw chunks into the current segment and snapshot buffer."""
        if self.wav_file is None:
            return

        for item in chunks:
            self.wav_file.writeframes(item)
            self.recorded_chunks.append(item)
            self.segment_chunks += 1

    def current_silence_seconds(self) -> float:
        """Return the current consecutive silence duration."""
        return self.silent_blocks * AUDIO_CHUNK_SECONDS

    def current_segment_seconds(self) -> float:
        """Return the current segment duration, including pre-roll."""
        return self.segment_chunks * AUDIO_CHUNK_SECONDS

    def update_silence_state(self, is_speech: bool) -> None:
        """Update silence counters and pause identity."""
        if is_speech:
            if self.silent_blocks > 0 or self.semantic_check_queued_this_pause:
                self.semantic_pause_index += 1
            self.silent_blocks = 0
            self.semantic_check_queued_this_pause = False
        else:
            self.silent_blocks += 1

    def should_queue_semantic_check(self) -> bool:
        """Return whether the current silence pause needs a semantic check."""
        return (
            not self.semantic_check_queued_this_pause
            and self.silent_blocks >= self.semantic_silence_blocks_needed
        )

    def handle_hard_silence_fallback(self) -> None:
        """Finish the segment unless endpoint ASR finds meaningful new words."""
        silence_seconds = self.current_silence_seconds()
        segment_seconds = self.current_segment_seconds()
        logger.info(
            "Audio segment fallback trigger: {:.1f}s silence since last "
            "speech chunk; segment duration {:.1f}s.",
            silence_seconds,
            segment_seconds,
        )

        new_words = self.fallback_new_words()
        if len(new_words) >= self.fallback_new_word_threshold:
            logger.info(
                "Audio segment fallback delayed: endpoint transcript gained {} new words.",
                len(new_words),
            )
            logger.debug("Fallback new-word suffix: {}", " ".join(new_words))
            self.semantic_pause_index += 1
            self.silent_blocks = 0
            self.semantic_check_queued_this_pause = False
            self.speech_detector.mark_speech()
            return

        logger.info(
            "Audio segment fallback accepted: no meaningful new words after {:.1f}s silence.",
            silence_seconds,
        )
        self.pending_completion_reason = f"{silence_seconds:.1f}s silence fallback"
        self.finish_segment_and_reset()

    def fallback_new_words(self) -> list[str]:
        """Return meaningful ASR tokens added since the latest semantic check."""
        if self.semantic_endpoint_detector is None or not self.recorded_chunks:
            return []

        draft_path = self.output_dir / (
            f"stream-segment-{self.segment_index:04d}-fallback-check.wav"
        )
        try:
            write_wav_file(draft_path, self.recorded_chunks)
            result = self.semantic_endpoint_detector(draft_path)
        except Exception as error:
            logger.warning("Fallback endpoint transcript check failed: {}", error)
            return []
        finally:
            draft_path.unlink(missing_ok=True)

        if result.is_gibberish:
            logger.debug(
                "Fallback endpoint transcript ignored as gibberish: {}",
                result.transcript,
            )
            return []

        if is_repetitive_transcript(result.transcript):
            logger.debug(
                "Fallback endpoint transcript ignored as repetitive: {}",
                result.transcript,
            )
            return []

        previous_transcript = self.latest_semantic_transcript
        self.latest_semantic_transcript = result.transcript
        return new_transcript_words(previous_transcript, result.transcript)

    def queue_semantic_endpoint_check(self) -> None:
        """Queue one semantic endpoint job for the current segment snapshot."""
        if (
            self.semantic_job_queue is None
            or self.segment_path is None
            or not self.recorded_chunks
        ):
            return

        self.semantic_job_queue.put(
            SemanticEndpointJob(
                segment_index=self.segment_index,
                pause_index=self.semantic_pause_index,
                chunks=list(self.recorded_chunks),
            )
        )
        logger.info(
            "Semantic endpoint check queued after {:g}s pause.",
            self.semantic_silence_seconds,
        )

    def handle_semantic_endpoint_results(self) -> bool:
        """Apply current semantic endpoint results without blocking capture."""
        if self.semantic_result_queue is None:
            return False

        while True:
            try:
                result = self.semantic_result_queue.get_nowait()
            except queue.Empty:
                return False

            if not self.recording_started:
                continue
            if self.semantic_result_is_stale(result):
                logger.debug(
                    "Ignoring stale semantic endpoint result for segment {} pause {}.",
                    result.segment_index,
                    result.pause_index,
                )
                continue

            if result.is_gibberish:
                logger.debug(
                    "Semantic endpoint transcript ignored as gibberish: {}",
                    result.transcript,
                )
                continue

            if is_repetitive_transcript(result.transcript):
                logger.debug(
                    "Semantic endpoint transcript ignored as repetitive: {}",
                    result.transcript,
                )
                continue

            self.latest_semantic_transcript = result.transcript

            if not result.is_complete:
                logger.debug("Semantic endpoint check: incomplete; waiting for more speech.")
                continue

            logger.info(
                "Audio segment trigger: semantic completion after {:g}s pause.",
                self.semantic_silence_seconds,
            )
            self.pending_completion_reason = (
                f"semantic completion after {self.semantic_silence_seconds:g}s pause"
            )
            self.finish_segment_and_reset()
            return True

    def semantic_result_is_stale(self, result: SemanticEndpointResult) -> bool:
        """Return whether a semantic result no longer matches current state."""
        return (
            result.segment_index != self.segment_index
            or result.pause_index != self.semantic_pause_index
        )


def stream_utterance_segments(
    output_dir: Path,
    segment_queue: queue.Queue[CompletedStreamSegment | Exception],
    stop_event: threading.Event,
    hard_silence_seconds: float = STREAM_HARD_SILENCE_SECONDS,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
    semantic_silence_seconds: float = STREAM_SEMANTIC_SILENCE_SECONDS,
    semantic_endpoint_detector: SemanticEndpointDetector | None = None,
    fallback_new_word_threshold: int = STREAM_FALLBACK_NEW_WORD_THRESHOLD,
) -> None:
    """Continuously record voice-triggered utterance segments to WAV files."""
    StreamSegmenter(
        output_dir=output_dir,
        segment_queue=segment_queue,
        stop_event=stop_event,
        hard_silence_seconds=hard_silence_seconds,
        silence_threshold=silence_threshold,
        semantic_silence_seconds=semantic_silence_seconds,
        semantic_endpoint_detector=semantic_endpoint_detector,
        fallback_new_word_threshold=fallback_new_word_threshold,
    ).run()


def run_semantic_endpoint_worker(
    output_dir: Path,
    job_queue: queue.Queue[SemanticEndpointJob | None],
    result_queue: queue.Queue[SemanticEndpointResult],
    semantic_endpoint_detector: SemanticEndpointDetector,
) -> None:
    """Run semantic endpoint checks away from the real-time recorder loop."""
    while True:
        job = job_queue.get()
        if job is None:
            return

        draft_path = output_dir / (
            f"stream-segment-{job.segment_index:04d}"
            f"-semantic-check-{job.pause_index:04d}.wav"
        )
        try:
            write_wav_file(draft_path, job.chunks)
            endpoint_result = semantic_endpoint_detector(draft_path)
        except Exception as error:
            logger.warning("Semantic endpoint check failed: {}", error)
            endpoint_result = SemanticEndpointResult(
                is_complete=False,
                segment_index=job.segment_index,
                pause_index=job.pause_index,
            )
        finally:
            draft_path.unlink(missing_ok=True)

        result_queue.put(
            SemanticEndpointResult(
                is_complete=endpoint_result.is_complete,
                transcript=endpoint_result.transcript,
                is_gibberish=endpoint_result.is_gibberish,
                segment_index=job.segment_index,
                pause_index=job.pause_index,
            )
        )


def normalize_transcript_words(transcript: str) -> list[str]:
    """Return lowercase word tokens for transcript comparison."""
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", transcript.lower())


def is_repetitive_transcript(transcript: str) -> bool:
    """Return whether a transcript looks like an ASR repetition loop."""
    words = normalize_transcript_words(transcript)
    return words_are_repetitive(words) or has_repetitive_suffix(words)


def words_are_repetitive(words: list[str], min_tokens: int = 20) -> bool:
    """Return whether the full token sequence looks repetitive."""
    if len(words) < min_tokens:
        return False

    unique_ratio = len(set(words)) / len(words)
    return unique_ratio <= 0.25 and max_ngram_coverage(words) >= 0.5


def has_repetitive_suffix(words: list[str], min_suffix_tokens: int = 12) -> bool:
    """Return whether a meaningful-looking transcript decays into a repeated suffix."""
    for suffix_length in range(min_suffix_tokens, len(words) + 1):
        suffix = words[-suffix_length:]
        unique_ratio = len(set(suffix)) / len(suffix)
        if unique_ratio <= 0.3 and max_ngram_coverage(suffix) >= 0.5:
            return True
    return False


def max_ngram_coverage(words: list[str], ngram_size: int = 3) -> float:
    """Return the largest repeated n-gram coverage ratio for the words."""
    if len(words) < ngram_size:
        return 0.0

    counts: dict[tuple[str, ...], int] = {}
    for index in range(len(words) - ngram_size + 1):
        ngram = tuple(words[index : index + ngram_size])
        counts[ngram] = counts.get(ngram, 0) + 1

    return max(counts.values()) * ngram_size / len(words)


def new_transcript_words(previous_transcript: str, current_transcript: str) -> list[str]:
    """Return tokens added after the longest common prefix."""
    if is_repetitive_transcript(current_transcript):
        return []

    previous_words = normalize_transcript_words(previous_transcript)
    current_words = normalize_transcript_words(current_transcript)
    common_prefix_length = 0

    for previous_word, current_word in zip(previous_words, current_words):
        if previous_word != current_word:
            break
        common_prefix_length += 1

    return current_words[common_prefix_length:]
