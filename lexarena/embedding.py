"""Text embedding behind one small interface (D-047).

The model and its limits come from config (`embedding.model`, `max_tokens`, `window_tokens`). The production
embedder runs the configured model with fastembed (ONNX, no PyTorch). Its tokenizer counts tokens with
truncation switched off, so long sections are split into windows by the caller instead of being silently
cut at the model's limit (SPEC B5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class Embedder(Protocol):
    dim: int

    def count_tokens(self, text: str) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def token_windows(text: str, count_tokens: Any, window_tokens: int) -> list[str]:
    """Split text on word boundaries into pieces of at most `window_tokens` tokens each."""
    if count_tokens(text) <= window_tokens:
        return [text]
    windows: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = [*current, word]
        if current and count_tokens(" ".join(candidate)) > window_tokens:
            windows.append(" ".join(current))
            current = [word]
        else:
            current = candidate
    if current:
        windows.append(" ".join(current))
    return windows


class FastEmbedder:
    def __init__(self, model: str, cache_dir: Path, batch_size: int) -> None:
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        self._model = TextEmbedding(model_name=model, cache_dir=str(cache_dir))
        self._batch_size = batch_size
        # A separate copy for counting: the model's own tokenizer keeps its settings for embedding.
        counter = Tokenizer.from_str(self._model.model.tokenizer.to_str())  # type: ignore[attr-defined]
        counter.no_truncation()
        counter.no_padding()
        self._tokenizer = counter
        self.dim = len(self.embed(["dimension probe"])[0])

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text).ids)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vector] for vector in self._model.embed(texts, batch_size=self._batch_size)]
