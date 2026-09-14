import asyncio
import uuid

from agents.buyer.graph import buyer_graph


# ============================================================
# BUYER AGENT CLI
# ============================================================

async def main():

    print("Buyer Agent")
    print("Type 'exit' to quit.\n")

    # --------------------------------------------------------
    # Session ID
    # --------------------------------------------------------
    #
    # We keep one session ID for the current CLI session.
    #
    # Later this can be connected to a database/checkpointer
    # so the conversation can survive application restarts.
    # --------------------------------------------------------

    session_id = str(uuid.uuid4())

    # --------------------------------------------------------
    # Keep the previous state in memory.
    #
    # This becomes important for:
    #
    # Cart → confirmation → purchase
    #
    # --------------------------------------------------------

    current_state = {
        "session_id": session_id,
    }

    while True:

        query = input("You: ")

        # ----------------------------------------------------
        # Exit
        # ----------------------------------------------------

        if query.lower().strip() == "exit":
            break

        if not query.strip():
            continue

        # ====================================================
        # HUMAN CONFIRMATION
        # ====================================================
        #
        # If the previous graph execution stopped with:
        #
        # awaiting_confirmation = True
        #
        # then this input is treated as the user's decision.
        # ====================================================

        if current_state.get(
            "awaiting_confirmation",
            False
        ):

            confirmation = query.lower().strip()

            if confirmation in {
                "yes",
                "y",
                "confirm",
                "proceed",
                "buy",
            }:

                print(
                    "\n→ Purchase confirmed by user.\n"
                )

                # --------------------------------------------
                # IMPORTANT
                #
                # We will wire the actual purchase continuation
                # into the graph/Razorpay flow next.
                # --------------------------------------------

                current_state[
                    "user_confirmation"
                ] = "yes"

                current_state[
                    "awaiting_confirmation"
                ] = False

                # For now, show that confirmation was received.
                print(
                    "Purchase confirmation received."
                )

                print(
                    "\nBUYER STATE:"
                )

                print(current_state)

                print()

                continue

            elif confirmation in {
                "no",
                "n",
                "cancel",
                "stop",
            }:

                print(
                    "\n→ Purchase cancelled.\n"
                )

                current_state[
                    "user_confirmation"
                ] = "no"

                current_state[
                    "awaiting_confirmation"
                ] = False

                current_state[
                    "purchase_ready"
                ] = False

                current_state[
                    "cart_payment_status"
                ] = "cancelled"

                current_state[
                    "cart_order_status"
                ] = "cancelled"

                print(
                    "\nBUYER STATE:"
                )

                print(current_state)

                print()

                continue

            else:

                print(
                    "\nPlease answer "
                    "'yes' or 'no'.\n"
                )

                continue

        # ====================================================
        # NORMAL SHOPPING REQUEST
        # ====================================================

        try:

            # ------------------------------------------------
            # Start a fresh shopping request while preserving
            # the session ID.
            # ------------------------------------------------

            result = await buyer_graph.ainvoke({
                "user_query": query,
                "session_id": session_id,
            })

            # ------------------------------------------------
            # Save the latest state.
            # ------------------------------------------------

            current_state = result

            # ------------------------------------------------
            # Display final response
            # ------------------------------------------------

            print()

            if result.get("final_response"):

                print(
                    result["final_response"]
                )

            # ------------------------------------------------
            # Display cart separately when available.
            # ------------------------------------------------

            cart = result.get(
                "cart"
            )

            if (
                cart
                and cart.get("items")
                and result.get("cart_complete")
            ):

                print(
                    "\nCart:"
                )

                for item in cart["items"]:

                    print(
                        f"- "
                        f"{item.get('product_name')} "
                        f"× {item.get('quantity')} "
                        f"from "
                        f"{item.get('merchant')} "
                        f"= ₹"
                        f"{item.get('total_price')}"
                    )

                print(
                    f"Total: ₹"
                    f"{cart.get('total', 0)}"
                )

            # ------------------------------------------------
            # If the graph asks for confirmation, tell user.
            # ------------------------------------------------

            if result.get(
                "awaiting_confirmation"
            ):

                print(
                    "\nProceed with purchase? "
                    "(yes/no)"
                )

            print(
                "\nBUYER STATE:"
            )

            print(result)

            print()

        except Exception as e:

            print(
                f"\nError: {e}\n"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
