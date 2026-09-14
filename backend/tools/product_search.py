from retrieval.vector_store import product_vector_store
from data.products import PRODUCTS


def exact_search(query: str):

    query = query.lower().strip()

    results = []

    for product in PRODUCTS:

        name = product["name"].lower()
        brand = product["brand"].lower()
        category = product["category"].lower()

        score = 0.0

        if query == name:
            score = 1.0

        elif query == brand:
            score = 0.95

        elif query == category:
            score = 0.90

        elif query in name:
            score = 0.85

        elif query in brand:
            score = 0.80

        elif query in category:
            score = 0.75

        if score > 0:
            results.append(
                {
                    "product": product,
                    "exact_score": score,
                }
            )

    return results


def search_products(
    query: str,
    top_k: int = 5,
):
    """
    Hybrid product retrieval.

    Combines:
    - exact / keyword search
    - vector semantic search

    Retrieval identifies candidates.
    It does NOT decide which product is best.
    """

    exact_results = exact_search(query)

    vector_results = product_vector_store.search(
        query,
        top_k=top_k,
    )

    candidates = {}

    # --------------------------------------------------------
    # Exact results
    # --------------------------------------------------------

    for result in exact_results:

        product = result["product"]

        candidates[product["id"]] = {
            "product": product,
            "exact_score": result["exact_score"],
            "vector_score": 0.0,
        }

    # --------------------------------------------------------
    # Vector results
    # --------------------------------------------------------

    for result in vector_results:

        product = result["product"]

        if product["id"] not in candidates:

            candidates[product["id"]] = {
                "product": product,
                "exact_score": 0.0,
                "vector_score": result["vector_score"],
            }

        else:

            candidates[
                product["id"]
            ]["vector_score"] = result["vector_score"]

    # --------------------------------------------------------
    # Hybrid ranking
    # --------------------------------------------------------

    results = []

    for candidate in candidates.values():

        exact_score = candidate["exact_score"]
        vector_score = candidate["vector_score"]

        # Exact matching gets stronger priority.
        hybrid_score = (
            0.6 * exact_score
            + 0.4 * vector_score
        )

        results.append(
            {
                "product": candidate["product"],
                "exact_score": round(
                    exact_score,
                    3,
                ),
                "vector_score": round(
                    vector_score,
                    3,
                ),
                "hybrid_score": round(
                    hybrid_score,
                    3,
                ),
            }
        )

    results.sort(
        key=lambda x: x["hybrid_score"],
        reverse=True,
    )

    return {
        "query": query,
        "candidates": results[:top_k],
    }