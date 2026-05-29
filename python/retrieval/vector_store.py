"""
ChromaDB vector store with numpy fallback.

Collections: sentence, utterance, topic, entity chunks per video.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from python.retrieval.chunker import Chunk

logger = logging.getLogger(__name__)

CHROMA_PATH = Path(os.path.expanduser("~/.axew/chroma_db"))

COLLECTION_MAP = {
    "sentence": "axew_sentence_chunks",
    "utterance": "axew_utterance_chunks",
    "topic": "axew_topic_chunks",
    "entity_context": "axew_entity_chunks",
    "scene_description": "axew_scene_descriptions",
}


class VectorStore:
    def __init__(self, use_chroma: bool = True) -> None:
        self._chroma_client = None
        self._collections: Dict[str, Any] = {}
        self._fallback: Dict[str, Dict[str, Any]] = {}
        self._use_chroma = use_chroma
        if use_chroma:
            try:
                import chromadb
                from chromadb.config import Settings

                CHROMA_PATH.mkdir(parents=True, exist_ok=True)
                self._chroma_client = chromadb.PersistentClient(
                    path=str(CHROMA_PATH),
                    settings=Settings(anonymized_telemetry=False),
                )
                logger.info("ChromaDB initialized at %s", CHROMA_PATH)
            except Exception as e:
                logger.warning("ChromaDB unavailable, using numpy fallback: %s", e)
                self._use_chroma = False

    def _get_collection(self, chunk_type: str):
        name = COLLECTION_MAP.get(chunk_type, f"axew_{chunk_type}_chunks")
        if not self._use_chroma or self._chroma_client is None:
            if name not in self._fallback:
                self._fallback[name] = {"ids": [], "embeddings": [], "metadatas": [], "documents": []}
            return self._fallback[name]

        if name not in self._collections:
            self._collections[name] = self._chroma_client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[name]

    def upsert_chunks(self, chunks: List[Chunk], chunk_type: str, video_id: str) -> None:
        if not chunks:
            return

        coll = self._get_collection(chunk_type)
        ids = [c.chunk_id for c in chunks]
        embeddings = [c.embedding for c in chunks if c.embedding]
        if len(embeddings) != len(chunks):
            raise ValueError("All chunks must have embeddings before upsert")

        metadatas = [
            {
                "video_id": video_id,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "speaker_id": c.speaker_id or "",
                "chunk_type": c.chunk_type,
                "entities": ",".join(c.entities[:20]),
                "events": ",".join(c.events[:20]),
                "sentiment": str(c.metadata.get("sentiment", "")),
                "emotion": str(c.metadata.get("emotion", "")),
            }
            for c in chunks
        ]
        documents = [c.text for c in chunks]

        if self._use_chroma and self._chroma_client is not None:
            coll.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            )
        else:
            coll["ids"] = ids
            coll["embeddings"] = [np.array(e, dtype=np.float32) for e in embeddings]
            coll["metadatas"] = metadatas
            coll["documents"] = documents

    def query_collection(
        self,
        query_embedding: np.ndarray,
        video_id: str,
        chunk_types: List[str],
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        results: List[Tuple[str, float, Dict[str, Any]]] = []
        q = np.asarray(query_embedding, dtype=np.float32)

        for ctype in chunk_types:
            coll = self._get_collection(ctype)
            if self._use_chroma and self._chroma_client is not None:
                where: Dict[str, Any] = {"video_id": video_id}
                if filters:
                    where.update(filters)
                try:
                    res = coll.query(
                        query_embeddings=[q.tolist()],
                        n_results=min(top_k, max(coll.count(), 1)),
                        where=where,
                    )
                    if res["ids"] and res["ids"][0]:
                        for i, cid in enumerate(res["ids"][0]):
                            dist = res["distances"][0][i] if res.get("distances") else 0.0
                            score = 1.0 - dist
                            meta = res["metadatas"][0][i] if res.get("metadatas") else {}
                            results.append((cid, score, meta))
                except Exception as e:
                    logger.warning("Chroma query failed: %s", e)
            else:
                for i, cid in enumerate(coll.get("ids", [])):
                    meta = coll["metadatas"][i]
                    if meta.get("video_id") != video_id:
                        continue
                    emb = coll["embeddings"][i]
                    score = float(np.dot(q, emb))
                    results.append((cid, score, meta))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def delete_video(self, video_id: str) -> None:
        if not self._use_chroma or self._chroma_client is None:
            self._fallback.clear()
            return
        for name in COLLECTION_MAP.values():
            try:
                coll = self._chroma_client.get_collection(name)
                coll.delete(where={"video_id": video_id})
            except Exception:
                pass

    def get_chunk_by_id(self, chunk_id: str, chunk_type: str = "sentence") -> Optional[Dict[str, Any]]:
        coll = self._get_collection(chunk_type)
        if self._use_chroma and self._chroma_client is not None:
            try:
                res = coll.get(ids=[chunk_id])
                if res["ids"]:
                    return {
                        "id": res["ids"][0],
                        "metadata": res["metadatas"][0] if res.get("metadatas") else {},
                        "document": res["documents"][0] if res.get("documents") else "",
                    }
            except Exception:
                return None
        else:
            for i, cid in enumerate(coll.get("ids", [])):
                if cid == chunk_id:
                    return {
                        "id": cid,
                        "metadata": coll["metadatas"][i],
                        "document": coll["documents"][i],
                    }
        return None
