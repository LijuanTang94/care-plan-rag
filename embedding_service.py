"""Embedding abstraction layer (same pattern as llm_service — provider is swappable).

  MockEmbedder      Deterministic fake vectors, no semantics — for testing / smoke-testing
                    the pipeline (free, no model download)
  FastEmbedEmbedder Real semantics (local ONNX small model bge-small, 384-dim, free)
  (In production / on Lambda you could add VoyageEmbedder / OpenAIEmbedder —
   Anthropic has no embedding API)

The EMBED_PROVIDER environment variable selects which one to use. Vector dimension is
fixed at 384 (to match the knowledge_chunks table).
"""

import hashlib
import os
from abc import ABC, abstractmethod
from functools import lru_cache

DIM = 384


class BaseEmbedder(ABC):
    dim = DIM

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """For documents (passages)."""
        ...

    def embed_query(self, query: str) -> list[float]:
        """For queries. Defaults to the same path as documents; asymmetric models like
        bge override this to prepend an instruction prefix."""
        return self.embed([query])[0]


class MockEmbedder(BaseEmbedder):
    """Hash-derived deterministic vectors. The same text always maps to the same vector,
    but there is no semantic similarity. For testing / validating the pipeline only;
    measuring real recall requires fastembed."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vals = [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(DIM)]
            norm = sum(v * v for v in vals) ** 0.5 or 1.0
            out.append([v / norm for v in vals])
        return out


class FastEmbedEmbedder(BaseEmbedder):
    """Real semantic embeddings: fastembed's BAAI/bge-small-en-v1.5 (384-dim). The model is downloaded on first use."""

    def __init__(self):
        from fastembed import TextEmbedding
        self.model = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self.model.embed(list(texts))]

    def embed_query(self, query: str) -> list[float]:
        # bge is asymmetric: the query must carry an instruction prefix, otherwise it lands in a different space from the passages and retrieval quality collapses
        q = "Represent this sentence for searching relevant passages: " + query
        return self.embed([q])[0]


_PROVIDERS = {
    "mock": MockEmbedder,
    "fastembed": FastEmbedEmbedder,
}


@lru_cache  # load the model only once
def get_embedder() -> BaseEmbedder:
    provider = os.environ.get("EMBED_PROVIDER", "mock")
    return _PROVIDERS.get(provider, MockEmbedder)()
