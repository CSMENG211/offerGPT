import queue
import tempfile
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audio import SemanticEndpointResult, StreamSegmenter
from audio.levels import audio_blocksize
from audio.segmenter import (
    StreamSpeechDetector,
    is_repetitive_transcript,
    new_transcript_words,
)
from speech.endpoint_detector import parse_gibberish_label


def silent_chunk() -> bytes:
    """Return one block of silence matching the app audio chunk size."""
    return b"\0" * audio_blocksize() * 2


def constant_chunk(level: int) -> bytes:
    """Return one block whose int16 samples all have the requested level."""
    sample = level.to_bytes(2, byteorder=sys.byteorder, signed=True)
    return sample * audio_blocksize()


def test_stream_speech_detector_hysteresis_and_hangover() -> None:
    detector = StreamSpeechDetector(
        start_threshold=500,
        continue_threshold_ratio=0.6,
        hangover_seconds=0.3,
    )

    assert not detector.is_speech(constant_chunk(350))
    assert detector.is_speech(constant_chunk(500))
    assert detector.is_speech(constant_chunk(350))
    assert detector.is_speech(silent_chunk())
    assert detector.is_speech(silent_chunk())
    assert detector.is_speech(silent_chunk())
    assert not detector.is_speech(silent_chunk())


def test_new_transcript_words() -> None:
    assert new_transcript_words("hello world", "hello world") == []
    assert new_transcript_words("Hello, WORLD!", "hello world") == []
    assert new_transcript_words("hello world", "hello brave") == ["brave"]
    assert new_transcript_words("hello world", "hello world from google") == [
        "from",
        "google",
    ]
    assert new_transcript_words(
        "return indices of the two numbers",
        "return indices of the two numbers that add up",
    ) == ["that", "add", "up"]


def test_repetitive_transcript_detection() -> None:
    repeated_transcript = "Some new ones, " + "maybe new ones, " * 24
    decayed_transcript = (
        "Given an array of integers, I would use a hash map. "
        + "maybe new ones, " * 8
    )
    normal_transcript = (
        "Given an array of integers and a target, return indices of two "
        "numbers that add up to the target."
    )

    assert is_repetitive_transcript(repeated_transcript)
    assert is_repetitive_transcript(decayed_transcript)
    assert not is_repetitive_transcript(normal_transcript)
    assert not is_repetitive_transcript("yes yes yes")
    assert new_transcript_words("hello world", repeated_transcript) == []
    assert new_transcript_words("hello world", decayed_transcript) == []


def test_gibberish_label_parsing() -> None:
    assert parse_gibberish_label("GIBBERISH") == "GIBBERISH"
    assert parse_gibberish_label("meaningful") == "MEANINGFUL"
    assert parse_gibberish_label("This is GIBBERISH.") == "OTHER:THIS IS GIBBERISH."
    assert parse_gibberish_label("unclear") == "OTHER:UNCLEAR"


def test_fallback_delays_when_endpoint_transcript_gains_words() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    def detector(_audio_path: Path) -> SemanticEndpointResult:
        return SemanticEndpointResult(
            is_complete=False,
            transcript="hello world from google today",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            hard_silence_seconds=0.2,
            semantic_endpoint_detector=detector,
        )
        segmenter.start_segment()
        segmenter.write_segment_chunks([silent_chunk()])
        segmenter.latest_semantic_transcript = "hello world"
        segmenter.silent_blocks = segmenter.hard_silence_blocks_needed

        segmenter.handle_hard_silence_fallback()

        assert segment_queue.empty()
        assert segmenter.recording_started
        assert segmenter.silent_blocks == 0
        assert segmenter.semantic_pause_index == 1


def test_fallback_accepts_when_endpoint_transcript_has_no_new_words() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    def detector(_audio_path: Path) -> SemanticEndpointResult:
        return SemanticEndpointResult(
            is_complete=False,
            transcript="hello world",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            hard_silence_seconds=0.2,
            semantic_endpoint_detector=detector,
        )
        segmenter.start_segment()
        segmenter.write_segment_chunks([silent_chunk()])
        segmenter.latest_semantic_transcript = "hello world"
        segmenter.silent_blocks = segmenter.hard_silence_blocks_needed

        segmenter.handle_hard_silence_fallback()

        completed = segment_queue.get_nowait()
        assert completed.completion_reason == "0.2s silence fallback"
        assert not segmenter.recording_started


def test_fallback_accepts_one_new_hallucinated_word() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    def detector(_audio_path: Path) -> SemanticEndpointResult:
        return SemanticEndpointResult(
            is_complete=False,
            transcript="hello world maybe",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            hard_silence_seconds=0.2,
            semantic_endpoint_detector=detector,
        )
        segmenter.start_segment()
        segmenter.write_segment_chunks([silent_chunk()])
        segmenter.latest_semantic_transcript = "hello world"
        segmenter.silent_blocks = segmenter.hard_silence_blocks_needed

        segmenter.handle_hard_silence_fallback()

        completed = segment_queue.get_nowait()
        assert completed.completion_reason == "0.2s silence fallback"
        assert not segmenter.recording_started


def test_fallback_accepts_repetitive_endpoint_transcript() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()
    repeated_transcript = "Some new ones, " + "maybe new ones, " * 24

    def detector(_audio_path: Path) -> SemanticEndpointResult:
        return SemanticEndpointResult(
            is_complete=False,
            transcript=repeated_transcript,
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            hard_silence_seconds=0.2,
            semantic_endpoint_detector=detector,
        )
        segmenter.start_segment()
        segmenter.write_segment_chunks([silent_chunk()])
        segmenter.latest_semantic_transcript = "hello world"
        segmenter.silent_blocks = segmenter.hard_silence_blocks_needed

        segmenter.handle_hard_silence_fallback()

        completed = segment_queue.get_nowait()
        assert completed.completion_reason == "0.2s silence fallback"
        assert not segmenter.recording_started


def test_fallback_accepts_model_gibberish_endpoint_transcript() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    def detector(_audio_path: Path) -> SemanticEndpointResult:
        return SemanticEndpointResult(
            is_complete=False,
            transcript="announce announce announce announce announce",
            is_gibberish=True,
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            hard_silence_seconds=0.2,
            semantic_endpoint_detector=detector,
        )
        segmenter.start_segment()
        segmenter.write_segment_chunks([silent_chunk()])
        segmenter.latest_semantic_transcript = "hello world"
        segmenter.silent_blocks = segmenter.hard_silence_blocks_needed

        segmenter.handle_hard_silence_fallback()

        completed = segment_queue.get_nowait()
        assert completed.completion_reason == "0.2s silence fallback"
        assert not segmenter.recording_started


def main() -> None:
    test_stream_speech_detector_hysteresis_and_hangover()
    test_new_transcript_words()
    test_repetitive_transcript_detection()
    test_gibberish_label_parsing()
    test_fallback_delays_when_endpoint_transcript_gains_words()
    test_fallback_accepts_when_endpoint_transcript_has_no_new_words()
    test_fallback_accepts_one_new_hallucinated_word()
    test_fallback_accepts_repetitive_endpoint_transcript()
    test_fallback_accepts_model_gibberish_endpoint_transcript()
    print("fallback guard tests passed")


if __name__ == "__main__":
    main()
