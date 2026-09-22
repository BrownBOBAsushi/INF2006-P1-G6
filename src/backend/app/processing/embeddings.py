"""Local sentence embeddings (all-MiniLM-L6-v2 at a pinned revision). No hosted API, no LLM.

- Weights load from the local Hugging Face cache only (`local_files_only=True`), so a request path can never
  trigger a hidden download. Fetch them once, explicitly:  python -m app.processing.embeddings --download
- The vector dimension is read from the loaded model and must equal EMBEDDING_DIM (the pgvector column size).
- Input is validated: empty text and text over the 240-token limit raise instead of being embedded/truncated.
- Vectors are unit-normalised float32; identical input gives identical output under the same environment.
"""
from __future__ import annotations

import argparse
from typing import Sequence

import numpy as np

from app.processing.chunking import TokenCounter
from app.processing.config import (
    EMBEDDING_DIM, EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_REVISION, EMBEDDING_VERSION, MAX_INPUT_TOKENS,
)
from app.processing.errors import EmptyTextError, TokenLimitError

_NORM_TOLERANCE = 1e-3


class EmbeddingModel:
    def __init__(self, name: str = EMBEDDING_MODEL_NAME, revision: str = EMBEDDING_MODEL_REVISION,
                 local_files_only: bool = True):
        import torch
        from sentence_transformers import SentenceTransformer
        from transformers import AutoTokenizer

        torch.set_num_threads(1)  # conservative default from ARCHITECTURE.md
        self.name, self.revision = name, revision
        self.version = EMBEDDING_VERSION if (name, revision) == (EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_REVISION) \
            else f"{name}@{revision}"
        self._model = SentenceTransformer(name, revision=revision, device="cpu", local_files_only=local_files_only)
        if getattr(self._model, "default_prompt_name", None):
            raise RuntimeError("model would silently prepend a prompt; refusing")
        self._model.max_seq_length = MAX_INPUT_TOKENS
        dim_fn = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = int(dim_fn())
        if self.dim != EMBEDDING_DIM:
            raise RuntimeError(f"model dimension {self.dim} != configured EMBEDDING_DIM {EMBEDDING_DIM}")
        self.counter = TokenCounter(AutoTokenizer.from_pretrained(name, revision=revision, local_files_only=local_files_only))

    def validate_text(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise EmptyTextError("cannot embed empty text")
        if self.counter.count(text) > MAX_INPUT_TOKENS:
            raise TokenLimitError(f"text exceeds {MAX_INPUT_TOKENS} tokens; chunk it first")

    def embed(self, texts: Sequence[str], batch_size: int = 16) -> np.ndarray:
        """Embed a batch. Returns float32 array of shape (len(texts), dim); row i corresponds to texts[i]."""
        if len(texts) == 0:
            return np.zeros((0, self.dim), dtype=np.float32)
        for t in texts:
            self.validate_text(t)
        vecs = self._model.encode(list(texts), batch_size=batch_size, normalize_embeddings=True,
                                  convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1)
        if not np.all(np.isfinite(vecs)) or np.any(np.abs(norms - 1.0) > _NORM_TOLERANCE):
            raise RuntimeError("embedding output is non-finite or not unit-normalised")
        return vecs

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def download_model() -> None:
    """Explicit, deliberate network step: cache the pinned weights (used at image build / first setup)."""
    EmbeddingModel(local_files_only=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Embedding model utilities")
    ap.add_argument("--download", action="store_true", help="download and cache the pinned model (network)")
    if ap.parse_args().download:
        download_model()
        print(f"cached {EMBEDDING_MODEL_NAME}@{EMBEDDING_MODEL_REVISION}")
