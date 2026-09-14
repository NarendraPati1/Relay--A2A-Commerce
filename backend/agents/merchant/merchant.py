from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.merchant.config import get_merchant_config


class MerchantState(TypedDict, total=False):
    merchant_id: str
    final_response: dict[str, Any]


class MerchantBrain:
    def __init__(self, merchant_id: str, config: dict[str, Any] | None = None):
        self.config = config or get_merchant_config(merchant_id)
        self.merchant_id = self.config["id"]
        self.graph = self._build_graph()

    def respond(self, state: MerchantState) -> dict[str, Any]:
        return {
            "final_response": {
                "merchant_id": self.merchant_id,
                "status": "ready",
                "message": "Merchant agent is ready for catalog requests.",
            }
        }

    def _build_graph(self):
        graph = StateGraph(MerchantState)
        graph.add_node("respond", self.respond)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        return graph.compile()


def create_merchant_agent(merchant_id: str = "dmart"):
    return MerchantBrain(merchant_id).graph
