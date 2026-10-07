"""Cross-encoder reranking behind one small interface (D-055).

The retrieval tools fetch `retrieval.candidate_pool` hits from Qdrant, then a cross-encoder reads the query and
each passage together and re-scores them, and the best `retrieval.top_k` are kept. The model comes from config
(`retrieval.reranker.model`) and runs with fastembed (ONNX, no PyTorch), like the embedder (D-047). Scoring is
deterministic for a given model and input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]: ...


class FastReranker:
    def __init__(self, model: str, cache_dir: Path, batch_size: int) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name=model, cache_dir=str(cache_dir))
        self._batch_size = batch_size

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self._model.rerank(query, passages, batch_size=self._batch_size)]
