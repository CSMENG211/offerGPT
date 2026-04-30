from pathlib import Path
import queue

from loguru import logger

from audio.stream_types import (
    SemanticEndpointDetector,
    SemanticEndpointJob,
    SemanticEndpointResult,
    StreamingTranscriber,
    TranscriptionJob,
    TranscriptionResult,
)
from audio.wav import write_wav_file


def run_transcription_worker(
    output_dir: Path,
    job_queue: queue.Queue[TranscriptionJob | None],
    result_queue: queue.Queue[TranscriptionResult],
    transcriber: StreamingTranscriber,
) -> None:
    """Run single-path streaming ASR on queued segment snapshots."""
    while True:
        job = job_queue.get()
        if job is None:
            return

        draft_path = output_dir / (
            f"stream-segment-{job.segment_index:04d}"
            f"-transcription-check-{job.pause_index:04d}.wav"
        )
        try:
            write_wav_file(draft_path, job.chunks)
            transcript = transcriber.transcribe(draft_path, log_progress=False)
            result = TranscriptionResult(
                transcript=transcript,
                is_rejected=False,
                segment_index=job.segment_index,
                pause_index=job.pause_index,
                start_chunk_index=job.start_chunk_index,
                end_chunk_index=job.end_chunk_index,
            )
        except Exception as error:
            logger.warning("Streaming transcription check failed: {}", error)
            result = TranscriptionResult(
                transcript="",
                is_rejected=True,
                segment_index=job.segment_index,
                pause_index=job.pause_index,
                start_chunk_index=job.start_chunk_index,
                end_chunk_index=job.end_chunk_index,
            )
        finally:
            draft_path.unlink(missing_ok=True)

        result_queue.put(result)


def run_semantic_endpoint_worker(
    job_queue: queue.Queue[SemanticEndpointJob | None],
    result_queue: queue.Queue[SemanticEndpointResult],
    semantic_endpoint_detector: SemanticEndpointDetector,
) -> None:
    """Run semantic endpoint checks away from the real-time recorder loop."""
    while True:
        job = job_queue.get()
        if job is None:
            return

        try:
            endpoint_result = semantic_endpoint_detector(job.transcript)
        except Exception as error:
            logger.warning("Semantic endpoint check failed: {}", error)
            endpoint_result = SemanticEndpointResult(
                is_complete=False,
                segment_index=job.segment_index,
                pause_index=job.pause_index,
            )

        result_queue.put(
            SemanticEndpointResult(
                is_complete=endpoint_result.is_complete,
                transcript=endpoint_result.transcript,
                is_rejected=endpoint_result.is_rejected,
                segment_index=job.segment_index,
                pause_index=job.pause_index,
                transcript_key=job.transcript_key,
            )
        )
