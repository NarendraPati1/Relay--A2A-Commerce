from __future__ import annotations

import sys

import uvicorn
from starlette.applications import Starlette

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from agents.merchant.config import get_merchant_config
from agents.merchant.merchant_executor import MerchantAgentExecutor


merchant_id = sys.argv[1] if len(sys.argv) > 1 else "dmart"
config = get_merchant_config(merchant_id)

agent_card = AgentCard(
    name=config["name"],
    description="Merchant Agent for product availability and price checks.",
    version="1.0.0",
    default_input_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=False),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url=f"http://127.0.0.1:{config['port']}",
            protocol_version="1.0",
        )
    ],
    skills=[
        AgentSkill(
            id="catalog",
            name="Catalog lookup",
            description="Check whether a product is available and return price and stock.",
            tags=["catalog", "inventory", "price"],
            examples=["Nescafe Classic 100g"],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

request_handler = DefaultRequestHandler(
    agent_executor=MerchantAgentExecutor(config),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)

routes = [
    *create_agent_card_routes(agent_card),
    *create_jsonrpc_routes(request_handler, "/"),
]
app = Starlette(routes=routes)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config["port"])
