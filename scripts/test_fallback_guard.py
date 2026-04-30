import queue
import tempfile
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audio import (
    SemanticEndpointResult,
    StreamSegmenter,
    TranscriptionResult,
)
from audio.levels import audio_blocksize


def silent_chunk() -> bytes:
    """Return one block of silence matching the app audio chunk size."""
    return b"\0" * audio_blocksize() * 2


class DummyTranscriber:
    def transcribe(self, _audio_path: Path, *, log_progress: bool = True) -> str:
        return ""


def attach_worker_queues(segmenter: StreamSegmenter) -> None:
    """Attach in-memory worker queues without starting threads."""
    segmenter.transcription_job_queue = queue.Queue()
    segmenter.transcription_result_queue = queue.Queue()
    segmenter.semantic_job_queue = queue.Queue()
    segmenter.semantic_result_queue = queue.Queue()


def test_transcript_agreement_queues_semantic_check() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            transcriber=DummyTranscriber(),
            semantic_endpoint_detector=lambda transcript: SemanticEndpointResult(
                is_complete=False,
                transcript=transcript,
            ),
            semantic_silence_seconds=0.1,
            transcript_agreement_count=2,
        )
        attach_worker_queues(segmenter)
        segmenter.start_segment()
        segmenter.silent_blocks = segmenter.semantic_silence_blocks_needed

        assert segmenter.transcription_result_queue is not None
        segmenter.transcription_result_queue.put(
            TranscriptionResult(
                transcript="hello world",
                segment_index=segmenter.segment_index,
                pause_index=segmenter.semantic_pause_index,
            )
        )
        segmenter.handle_transcription_results()

        assert segmenter.semantic_job_queue is not None
        assert segmenter.semantic_job_queue.empty()

        segmenter.transcription_result_queue.put(
            TranscriptionResult(
                transcript="hello world",
                segment_index=segmenter.segment_index,
                pause_index=segmenter.semantic_pause_index,
            )
        )
        segmenter.handle_transcription_results()

        semantic_job = segmenter.semantic_job_queue.get_nowait()
        assert semantic_job.transcript == "hello world"


def test_hard_silence_cuts_segment_with_latest_transcript() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            transcriber=DummyTranscriber(),
            hard_silence_seconds=0.1,
        )
        segmenter.start_segment()
        segmenter.latest_transcript = "stable answer"
        segmenter.silent_blocks = segmenter.hard_silence_blocks_needed

        segmenter.accept_hard_silence()

        completed = segment_queue.get_nowait()
        assert completed.transcript == "stable answer"
        assert completed.completion_reason == "0.1s hard silence"


def test_semantic_completion_cuts_current_segment() -> None:
    segment_queue: queue.Queue[object] = queue.Queue()

    with tempfile.TemporaryDirectory() as temp_dir:
        segmenter = StreamSegmenter(
            output_dir=Path(temp_dir),
            segment_queue=segment_queue,
            stop_event=threading.Event(),
            transcriber=DummyTranscriber(),
            semantic_silence_seconds=0.1,
        )
        attach_worker_queues(segmenter)
        segmenter.start_segment()
        segmenter.latest_transcript = "I would use a hash map"

        assert segmenter.semantic_result_queue is not None
        segmenter.semantic_result_queue.put(
            SemanticEndpointResult(
                is_complete=True,
                transcript="I would use a hash map",
                segment_index=segmenter.segment_index,
                pause_index=segmenter.semantic_pause_index,
            )
        )

        completed = segmenter.handle_semantic_endpoint_results()

        assert completed
        queued_segment = segment_queue.get_nowait()
        assert queued_segment.transcript == "I would use a hash map"
        assert queued_segment.completion_reason == "semantic completion after 0.1s pause"


def main() -> None:
    test_transcript_agreement_queues_semantic_check()
    test_hard_silence_cuts_segment_with_latest_transcript()
    test_semantic_completion_cuts_current_segment()
    print("streaming transcript tests passed")


if __name__ == "__main__":
    main()
