import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "ai-service"))

MEDIA_PATH = r"D:\Dev\Project\Video_Editor\assets\input.mp4"
VIDEO_ID = "default"
MODEL = "large-v3"
LOG_PATH = PROJECT_ROOT / "data" / VIDEO_ID / "run.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def main() -> None:
    from config import settings
    from python.enrichment.builder import build_enriched_transcript
    from python.intelligence.extraction_pipeline import extract_intelligence
    from python.retrieval.video_index import VideoIndex
    from python.transcription.pipeline import process_media

    log(f"config default_whisper_model={settings.default_whisper_model}")
    log(f"starting process_media model={MODEL} video_id={VIDEO_ID}")
    t0 = time.time()
    result = await process_media(
        MEDIA_PATH,
        video_id=VIDEO_ID,
        model_name=MODEL,
        language=None,
        skip_correction=True,
        skip_topic_label=True,
    )
    proc_elapsed = time.time() - t0
    log(f"process_media done in {proc_elapsed:.1f}s")

    doc = result["document"]
    meta = dict(doc.get("metadata") or {})
    meta.update(
        {
            "whisper_model": MODEL,
            "media_path": MEDIA_PATH,
            "word_timestamps": True,
            "pipeline": "process_media",
        }
    )

    segments = []
    for i, utt in enumerate(doc.get("utterances", [])):
        segments.append(
            {
                "id": str(i),
                "start": utt["start"],
                "end": utt["end"],
                "text": utt.get("raw_text", ""),
                "speaker": utt.get("speaker_id"),
                "words": [
                    {
                        "word": w["text"],
                        "start": w["start"],
                        "end": w["end"],
                        "confidence": w.get("confidence", 0.0),
                    }
                    for w in utt.get("words", [])
                ],
            }
        )

    log("building enriched transcript")
    build_enriched_transcript(segments, video_id=VIDEO_ID)

    out_path = PROJECT_ROOT / "data" / VIDEO_ID / "transcript_enriched.json"
    enriched = json.loads(out_path.read_text(encoding="utf-8"))
    enriched["metadata"] = meta
    out_path.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    log(f"persisted enriched transcript -> {out_path}")

    log("indexing vectors + BM25")
    artifacts = await extract_intelligence(segments, video_id=VIDEO_ID, skip_topic_label=True)
    index = VideoIndex(artifacts, VIDEO_ID)
    index.index()
    log("indexing complete")

    summary = {
        "video_id": VIDEO_ID,
        "transcription_elapsed_sec": round(proc_elapsed, 1),
        "total_elapsed_sec": round(time.time() - t0, 1),
        "duration_sec": doc.get("duration_sec"),
        "segment_count": len(segments),
        "word_count": len(doc.get("words", [])),
        "whisper_model": MODEL,
        "config_default": settings.default_whisper_model,
        "transcript_path": str(out_path),
        "metadata": meta,
        "chunk_counts": result.get("chunk_counts", {}),
    }
    print("===SUMMARY===")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
