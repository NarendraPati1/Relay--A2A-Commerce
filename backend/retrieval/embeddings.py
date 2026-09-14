from pathlib import Path

from sentence_transformers import SentenceTransformer


MODEL_NAME = "all-MiniLM-L6-v2"

MODEL_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "models"
    / "all-MiniLM-L6-v2"
)


def get_model():
    """
    Load the embedding model from the local project directory.

    The model must already exist locally.
    No Hugging Face download is allowed at runtime.
    """
    if not MODEL_DIR.exists():
        raise FileNotFoundError(
            f"Local embedding model not found at:\n{MODEL_DIR}\n\n"
            "Run the model download/setup step first."
        )

    return SentenceTransformer(
        str(MODEL_DIR),
        local_files_only=True,
    )


model = get_model()


def create_product_text(product: dict) -> str:
    return (
        f"{product['name']}. "
        f"{product['description']}. "
        f"Category: {product['category']}. "
        f"Brand: {product['brand']}. "
        f"Pack size: {product['pack_size']}."
    )


def embed_products(products: list[dict]):
    texts = [create_product_text(product) for product in products]

    return model.encode(
        texts,
        normalize_embeddings=True,
    )


def embed_query(query: str):
    return model.encode(
        [query],
        normalize_embeddings=True,
    )