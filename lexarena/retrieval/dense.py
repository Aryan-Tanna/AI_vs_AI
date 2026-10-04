"""Optional dense embeddings (bge-m3 by default, loaded from the local Hugging Face cache only).

Embeddings are computed once by `python -m lexarena.retrieval.build_index --dense` and cached as .npy next to
a hash of the unit texts; a stale cache is ignored. At ~20k units a brute-force dot product is fast enough;
Qdrant can replace this behind the same interface if the corpus grows.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

DEFAULT_MODEL = "BAAI/bge-m3"


def texts_hash(texts: list[str], model: str) -> str:
    h = hashlib.sha256(model.encode())
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


class DenseIndex:
    def __init__(self, vectors: np.ndarray, model_name: str):
        self.vectors, self.model_name, self._model = vectors, model_name, None

    def _encoder(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, local_files_only=True)
        return self._model

    def scores(self, query: str) -> np.ndarray:
        q = self._encoder().encode([query], normalize_embeddings=True)[0]
        return self.vectors @ q

    @staticmethod
    def build(texts: list[str], model_name: str = DEFAULT_MODEL, batch_size: int = 32) -> np.ndarray:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name, local_files_only=True)
        model.max_seq_length = 512
        return model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=True).astype(np.float32)

    @classmethod
    def load(cls, dir_: Path, texts: list[str], model_name: str = DEFAULT_MODEL) -> "DenseIndex | None":
        meta, vec = dir_ / "dense_meta.json", dir_ / "dense.npy"
        if not (meta.exists() and vec.exists()):
            return None
        m = json.loads(meta.read_text(encoding="utf-8"))
        if m.get("hash") != texts_hash(texts, model_name):
            return None
        return cls(np.load(vec), model_name)

    @staticmethod
    def save(dir_: Path, vectors: np.ndarray, texts: list[str], model_name: str = DEFAULT_MODEL) -> None:
        dir_.mkdir(parents=True, exist_ok=True)
        np.save(dir_ / "dense.npy", vectors)
        (dir_ / "dense_meta.json").write_text(json.dumps({"model": model_name, "hash": texts_hash(texts, model_name),
                                                          "n": len(texts)}), encoding="utf-8")
