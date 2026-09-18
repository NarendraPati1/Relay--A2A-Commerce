"""Optional local cross-encoder reranking for product retrieval.

The embedding index remains the fast first stage. This module scores only its
short candidate list, avoiding a cloud model call for every catalogue lookup.
"""

import os
from pathlib import Path

from sentence_transformers import CrossEncoder

from retrieval.embeddings import create_product_text


RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "models"
    / "cross-encoder-ms-marco-MiniLM-L6-v2"
)


def _enabled() -> bool:
    return os.getenv("BUYER_CROSS_ENCODER_ENABLED", "false").lower() in {
        "1", "true", "yes",
    }


class ProductReranker:
    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            if not RERANKER_DIR.exists():
                raise FileNotFoundError(
                    "Cross-encoder is enabled but its local model is missing: "
                    f"{RERANKER_DIR}"
                )
            self._model = CrossEncoder(
                str(RERANKER_DIR),
                local_files_only=True,
            )
        return self._model

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Return the same candidates ordered by query-to-product relevance."""
        if not _enabled() or len(candidates) < 2:
            return candidates

        model = self._get_model()
        scores = model.predict([
            (query, create_product_text(candidate["product"]))
            for candidate in candidates
        ])
        scored = [
            {**candidate, "cross_encoder_score": float(score)}
            for candidate, score in zip(candidates, scores, strict=True)
        ]
        return sorted(
            scored,
            key=lambda candidate: candidate["cross_encoder_score"],
            reverse=True,
        )

    def rerank_many(
        self,
        requests: list[tuple[str, list[dict]]],
        batch_size: int = 64,
    ) -> list[list[dict]]:
        """Rerank many independent queries in one model batch for evaluation."""
        if not _enabled():
            return [candidates for _, candidates in requests]

        model = self._get_model()
        pairs = []
        spans = []
        for query, candidates in requests:
            start = len(pairs)
            pairs.extend(
                (query, create_product_text(candidate["product"]))
                for candidate in candidates
            )
            spans.append((start, len(pairs), candidates))

        scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
        reranked = []
        for start, end, candidates in spans:
            scored = [
                {**candidate, "cross_encoder_score": float(score)}
                for candidate, score in zip(candidates, scores[start:end], strict=True)
            ]
            reranked.append(sorted(
                scored,
                key=lambda candidate: candidate["cross_encoder_score"],
                reverse=True,
            ))
        return reranked


product_reranker = ProductReranker()
