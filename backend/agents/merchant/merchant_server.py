from __future__ import annotations

import sys

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.middleware.cors import CORSMiddleware

from agents.merchant.config import get_merchant_config
from agents.merchant.commerce import MerchantCommerceService
from agents.merchant.merchant_executor import MerchantAgentExecutor


merchant_id = sys.argv[1] if len(sys.argv) > 1 else "dmart"
config = get_merchant_config(merchant_id)
merchant_service = MerchantCommerceService(
    merchant_id=config["id"],
    merchant_name=config["name"],
    inventory=config["inventory"],
    discount_rules=config.get("discount_rules", []),
    recommendation_policy=config.get("recommendation_policy", {}),
)

agent_card = AgentCard(
    name=config["name"],
    description="Merchant Agent for offers, upsell/cross-sell-ready negotiations, audit records, and payment-order creation.",
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
            description="Check offers, negotiate legitimate bulk pricing, and create idempotent merchant payment orders.",
            tags=["catalog", "inventory", "price", "negotiation", "payments", "audit"],
            examples=["Nescafe Classic 100g"],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

request_handler = DefaultRequestHandler(
    agent_executor=MerchantAgentExecutor(config, service=merchant_service),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)

async def verify_payment(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        verified = merchant_service.verify_payment(
            transaction_id=str(payload["transaction_id"]),
            order_id=str(payload["razorpay_order_id"]),
            payment_id=str(payload["razorpay_payment_id"]),
            signature=str(payload["razorpay_signature"]),
        )
        return JSONResponse({"verified": verified}, status_code=200 if verified else 400)
    except (KeyError, ValueError, RuntimeError):
        return JSONResponse({"verified": False}, status_code=400)


routes = [
    *create_agent_card_routes(agent_card),
    *create_jsonrpc_routes(request_handler, "/"),
    Route("/v1/payments/verify", verify_payment, methods=["POST"]),
]
app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    # The demo checkout page is served by the buyer at this local origin.
    # Deployments must replace this with their authenticated HTTPS UI origin.
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["POST"],
    allow_headers=["content-type"],
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config["port"])
