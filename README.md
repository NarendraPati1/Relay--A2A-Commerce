# Relay — Autonomous Agent-to-Agent (A2A) Commerce Engine

**Relay** is a production-grade multi-agent commerce system built on Google's **Agent-to-Agent (A2A) protocol** and **LangGraph**. It transforms unstructured natural language requests into structured shopping goals, queries distributed live merchant agents via asynchronous JSON-RPC, evaluates real-time inventory and pricing, negotiates volume discounts, and reconciles transactions with human-in-the-loop cryptographic payment verification.

![Relay homepage](docs/images/hero-ui.png)

Relay orchestrates distributed buyer-to-merchant commerce workflows — converting natural language into structured shopping goals, querying live A2A merchant agents, comparing verified offers, and executing secure settlements under strict human confirmation.

> **Documentation**
>
> - [System Architecture](docs/architecture.md) — How the Buyer Agent, Merchant Agents, memory, retrieval, A2A communication, and payment boundaries work.
> - [Interactive Demo](docs/demo.md) — Screenshots and a simple walkthrough of the workspace, cart negotiation, and checkout settlement.
> - [Open the local demo](frontend/index.html) — Open the frontend directly, or run the backend first for the full interactive experience.

## Demo

The demo page contains the UI screenshots and a short explanation of the main user flow:

- [View the demo screenshots](docs/demo.md)
- [Open the local workspace](frontend/index.html)

## Architecture

The architecture diagram and all technical design details are kept in one place:

- [Read the architecture documentation](docs/architecture.md)

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Groq API key
- Razorpay test key pair

### Install and configure

```bash
git clone <repo-url>
cd after
cp .env.example .env
uv sync
```

Set these values in `.env`:

```env
GROQ_API_KEY=gsk_your_groq_api_key
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_razorpay_secret
BUYER_MODEL=openai/gpt-oss-120b
BUYER_REASONING_TEMPERATURE=0.2
A2A_AUTO_START_MERCHANTS=true
```

### Build the product index

```bash
uv run python -m retrieval.indexer
```

### Start Relay

```bash
uv run uvicorn agents.buyer.buyer_server:app --reload --port 8000 --app-dir backend
```

Open `http://localhost:8000` in your browser.

## Docker

```bash
docker compose up --build
```

## Tests

```bash
uv run pytest -v
```

The test suite covers the buyer workflow, durable memory, merchant inventory and discounts, payment verification, HTTP routes, and SSE streaming.

## API Summary

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Landing page and workspace |
| `GET` | `/health` | Health check |
| `POST` | `/v1/buyer/messages` | Process a buyer message |
| `POST` | `/v1/buyer/messages/stream` | Process a message with SSE progress events |
| `GET` | `/.well-known/agent-card.json` | Merchant A2A Agent Card |
| `POST` | `/v1/payments/verify` | Verify a merchant payment signature |

## Security in Brief

Relay keeps payment authority inside the selected Merchant Agent. The Buyer Agent waits for explicit human approval, never receives merchant payment secrets, and relies on merchant-side HMAC verification before an order is marked complete.
