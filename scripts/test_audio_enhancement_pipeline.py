import queue
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app
import audio.segmenter as segmenter
from audio import CompletedStreamSegment, SemanticEndpointJob, TranscriptionJob
from audio.levels import audio_blocksize
from audio.wav import write_wav_file
from speech import SpeakerHint


def silent_chunk() -> bytes:
    """Return one block of silence matching the app audio chunk size."""
    return b"\0" * audio_blocksize() * 2


class RecordingSpeakerIdentifier:
    def __init__(self) -> None:
        self.path: Path | None = None

    def match(self, audio_path: Path) -> SpeakerHint:
        self.path = audio_path
        assert audio_path.exists()
        return SpeakerHint(
            role_hint="unknown",
            confidence=None,
            similarity=None,
            profile_available=False,
        )


class RecordingTranscriber:
    def __init__(self) -> None:
        self.path: Path | None = None

    def transcribe(self, audio_path: Path, *, log_progress: bool = True) -> str:
        self.path = audio_path
        assert audio_path.exists()
        return "hello world"


def test_process_stream_segment_uses_streamed_transcript_and_raw_audio() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        raw_path = Path(temp_dir) / "stream-segment-0001.wav"
        write_wav_file(raw_path, [silent_chunk()])
        speaker_identifier = RecordingSpeakerIdentifier()
        options = app.RuntimeOptions(ask_chatgpt=False)

        submitted = app.process_stream_segment(
            CompletedStreamSegment(raw_path, "test", transcript="hello world"),
            speaker_identifier,
            options,
            include_mode_prompt=True,
            photo_tracker=app.PhotoUploadTracker(),
        )

        assert not submitted
        assert speaker_identifier.path == raw_path
        assert not raw_path.exists()


def test_transcription_worker_uses_snapshot_audio_and_cleans_temp_files() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        job_queue: queue.Queue[TranscriptionJob | None] = queue.Queue()
        result_queue: queue.Queue[segmenter.TranscriptionResult] = queue.Queue()
        transcriber = RecordingTranscriber()

        worker = threading.Thread(
            target=segmenter.run_transcription_worker,
            args=(
                output_dir,
                job_queue,
                result_queue,
                transcriber,
            ),
        )
        worker.start()
        job_queue.put(
            TranscriptionJob(
                segment_index=1,
                pause_index=2,
                chunks=[silent_chunk()],
            )
        )
        job_queue.put(None)
        worker.join(timeout=3)

        assert not worker.is_alive()
        assert transcriber.path == output_dir / "stream-segment-0001-transcription-check-0002.wav"
        assert result_queue.get_nowait().transcript == "hello world"
        assert not transcriber.path.exists()


def test_semantic_worker_classifies_stabilized_text() -> None:
    job_queue: queue.Queue[SemanticEndpointJob | None] = queue.Queue()
    result_queue: queue.Queue[segmenter.SemanticEndpointResult] = queue.Queue()

    def detector(transcript: str) -> segmenter.SemanticEndpointResult:
        assert transcript == "stable answer"
        return segmenter.SemanticEndpointResult(is_complete=True, transcript=transcript)

    worker = threading.Thread(
        target=segmenter.run_semantic_endpoint_worker,
        args=(
            job_queue,
            result_queue,
            detector,
        ),
    )
    worker.start()
    job_queue.put(
        SemanticEndpointJob(
            segment_index=1,
            pause_index=2,
            transcript="stable answer",
        )
    )
    job_queue.put(None)
    worker.join(timeout=3)

    result = result_queue.get_nowait()
    assert result.is_complete
    assert result.transcript == "stable answer"


def main() -> None:
    test_process_stream_segment_uses_streamed_transcript_and_raw_audio()
    test_transcription_worker_uses_snapshot_audio_and_cleans_temp_files()
    test_semantic_worker_classifies_stabilized_text()
    print("streaming pipeline tests passed")


if __name__ == "__main__":
    main()
