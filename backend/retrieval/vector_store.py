import json
from pathlib import Path

import faiss

from retrieval.embeddings import embed_query, MODEL_NAME


INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "index"
INDEX_PATH = INDEX_DIR / "products.faiss"
METADATA_PATH = INDEX_DIR / "metadata.json"


class ProductVectorStore:

    def __init__(self):
        if not INDEX_PATH.exists() or not METADATA_PATH.exists():
            raise FileNotFoundError(
                "Product index not found.\n"
                "Run:\n"
                "uv run python -m retrieval.indexer"
            )

        print("Loading persisted product index...")

        self.index = faiss.read_index(str(INDEX_PATH))

        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # Make sure the same embedding model is being used.
        if metadata["model"] != MODEL_NAME:
            raise ValueError(
                f"Embedding model mismatch. "
                f"Index uses {metadata['model']}, "
                f"but application uses {MODEL_NAME}."
            )

        self.products = metadata["products"]

        if self.index.ntotal != len(self.products):
            raise ValueError(
                "FAISS index and product metadata are out of sync."
            )

    def search(self, query: str, top_k: int = 5):

        query_embedding = embed_query(query)

        scores, indices = self.index.search(
            query_embedding,
            min(top_k, len(self.products)),
        )

        results = []

        for score, index in zip(scores[0], indices[0]):
            product = self.products[index]

            results.append({
                "product": product,
                "vector_score": float(score),
            })

        return results


product_vector_store = ProductVectorStore()