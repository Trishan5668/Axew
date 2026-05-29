from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.video_index import VideoIndex


class RetrievalStrategy(ABC):
    @abstractmethod
    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        ...
