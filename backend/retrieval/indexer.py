import json
from pathlib import Path

import faiss

from data.products import PRODUCTS
from retrieval.embeddings import embed_products, MODEL_NAME


INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "index"
INDEX_PATH = INDEX_DIR / "products.faiss"
METADATA_PATH = INDEX_DIR / "metadata.json"


def build_index():
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    print("Building product embeddings...")

    embeddings = embed_products(PRODUCTS)

    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    faiss.write_index(index, str(INDEX_PATH))

    metadata = {
        "model": MODEL_NAME,
        "dimension": dimension,
        "products": PRODUCTS,
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"Index saved to: {INDEX_PATH}")
    print(f"Metadata saved to: {METADATA_PATH}")
    print(f"Indexed {len(PRODUCTS)} products.")


if __name__ == "__main__":
    build_index()