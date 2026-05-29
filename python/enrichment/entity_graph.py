"""SQLite entity timeline graph."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class EntityMention:
    entity_id: str
    start_ms: int
    end_ms: int
    segment_id: str
    confidence: float


@dataclass
class EntityRecord:
    canonical_name: str
    aliases: List[str]
    entity_type: str
    mentions: List[EntityMention] = field(default_factory=list)
    speaker_ids: List[str] = field(default_factory=list)
    entity_id: str = ""


class EntityTimelineGraph:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT,
                    type TEXT,
                    aliases_json TEXT
                );
                CREATE TABLE IF NOT EXISTS mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT,
                    start_ms INTEGER,
                    end_ms INTEGER,
                    segment_id TEXT,
                    confidence REAL
                );
                CREATE TABLE IF NOT EXISTS relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id_a TEXT,
                    entity_id_b TEXT,
                    relation_type TEXT,
                    segment_id TEXT
                );
                """
            )

    def build(self, entity_records: List[EntityRecord]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM entities")
            conn.execute("DELETE FROM mentions")
            conn.execute("DELETE FROM relations")
            for rec in entity_records:
                eid = rec.entity_id or rec.canonical_name.lower().replace(" ", "_")
                conn.execute(
                    "INSERT INTO entities VALUES (?,?,?,?)",
                    (eid, rec.canonical_name, rec.entity_type, json.dumps(rec.aliases)),
                )
                for m in rec.mentions:
                    conn.execute(
                        "INSERT INTO mentions (entity_id, start_ms, end_ms, segment_id, confidence) VALUES (?,?,?,?,?)",
                        (eid, m.start_ms, m.end_ms, m.segment_id, m.confidence),
                    )

    def query_entity_windows(self, entity_name: str) -> List[Tuple[int, int]]:
        key = entity_name.lower()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT m.start_ms, m.end_ms FROM mentions m
                JOIN entities e ON e.id = m.entity_id
                WHERE lower(e.canonical_name) LIKE ? OR e.aliases_json LIKE ?
                """,
                (f"%{key}%", f"%{key}%"),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def query_entity_coappearance(
        self, entity_a: str, entity_b: str, window_ms: int = 30_000
    ) -> List[Tuple[int, int]]:
        wins_a = self.query_entity_windows(entity_a)
        wins_b = self.query_entity_windows(entity_b)
        results: List[Tuple[int, int]] = []
        for sa, ea in wins_a:
            for sb, eb in wins_b:
                if abs(sa - sb) <= window_ms or (sa <= eb and sb <= ea):
                    results.append((min(sa, sb), max(ea, eb)))
        return results
