import asyncio
import argparse
import os
import uuid

from agents.buyer.graph import buyer_graph
from agents.buyer.service import BuyerService


async def main(buyer_id: str | None = None):
    print("Buyer Agent")
    print("Type 'exit' to quit.\n")

    session_id = str(uuid.uuid4())
    buyer_id = buyer_id or os.getenv("BUYER_ID") or f"session:{session_id}"
    buyer_service = BuyerService(buyer_graph)

    while True:
        query = input("You: ").strip()

        if query.lower() == "exit":
            break

        if not query:
            continue

        try:
            result = await buyer_service.send_message(
                message=query,
                session_id=session_id,
                buyer_id=buyer_id,
            )

            print()
            print(result["reply"])

            cart = result.get("cart") or {}
            if cart.get("items"):
                print("\nCart:")
                for item in cart["items"]:
                    print(
                        f"- {item.get('product_name')} × "
                        f"{item.get('quantity')} from "
                        f"{item.get('merchant')} = ₹"
                        f"{item.get('total_price')}"
                    )
                print(f"Total: ₹{cart.get('total', 0)}")

            if result["checkout"].get("awaiting_confirmation"):
                print("\nAwaiting your confirmation.")
            print()

        except Exception as exc:
            print(f"\nError: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--buyer-id",
        help="Stable non-secret identifier to reuse preferences across sessions.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.buyer_id))
