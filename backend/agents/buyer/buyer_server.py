"""HTTP entry point for the buyer agent.

Run locally from ``backend`` with:
    uv run uvicorn agents.buyer.buyer_server:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import asyncio
import json
import sys
import subprocess
from http import HTTPStatus
from contextlib import asynccontextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"
_CHECKOUT_PAGE = _FRONTEND_DIR / "index.html"
_BACKEND_DIR = _PROJECT_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from agents.buyer.graph import buyer_graph
from agents.buyer.progress import reset_progress_reporter, set_progress_reporter
from agents.buyer.service import BuyerService

load_dotenv(_PROJECT_ROOT / ".env")


class BuyerMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = Field(default=None, max_length=128)
    buyer_id: str | None = Field(default=None, max_length=128)


buyer_service = BuyerService(buyer_graph)
logger = logging.getLogger(__name__)


async def _port_is_open(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=0.25,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError):
        return False


@asynccontextmanager
async def lifespan(_: Starlette):
    """Launch the bundled local merchant agents for the interactive demo.

    An already-running merchant is left alone.  Set
    ``A2A_AUTO_START_MERCHANTS=false`` when connecting the buyer to separately
    managed merchant services.
    """
    processes: list[subprocess.Popen] = []
    if os.getenv("A2A_AUTO_START_MERCHANTS", "true").lower() not in {"0", "false", "no"}:
        from agents.merchant.config import MERCHANTS

        for merchant_id, merchant in MERCHANTS.items():
            if await _port_is_open(int(merchant["port"])):
                continue
            process = subprocess.Popen(
                [sys.executable, "-m", "agents.merchant.merchant_server", merchant_id],
                cwd=str(_BACKEND_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
        if processes:
            # Give local Uvicorn processes a brief head start before the first
            # browser request; discovery still performs its own availability check.
            await asyncio.sleep(0.35)
    try:
        yield
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        if processes:
            for process in processes:
                try:
                    await asyncio.to_thread(process.wait, timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "buyer-agent"})


async def checkout_page(_: Request) -> FileResponse:
    return FileResponse(_CHECKOUT_PAGE, media_type="text/html")


async def stylesheet(_: Request) -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "style.css", media_type="text/css")


async def frontend_script(_: Request) -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "app.js", media_type="application/javascript")


async def checkout_config(_: Request) -> JSONResponse:
    """Expose Razorpay's public key only; the secret never leaves a merchant."""
    key_id = os.getenv("RAZORPAY_KEY_ID")
    if not key_id:
        return JSONResponse(
            {"detail": "Razorpay test checkout is not configured."},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    return JSONResponse({"key_id": key_id, "currency": "INR"})


async def send_message(request: Request) -> JSONResponse:
    try:
        body = BuyerMessageRequest.model_validate(await request.json())
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Request body must contain a valid message and optional session_id.",
        ) from exc

    try:
        result = await buyer_service.send_message(
            message=body.message,
            session_id=body.session_id,
            buyer_id=body.buyer_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        # Keep provider/A2A failures out of the public response while leaving
        # the full exception in application logs for operators.
        logger.exception("Buyer turn failed")
        raise HTTPException(
            status_code=HTTPStatus.BAD_GATEWAY,
            detail="The buyer agent could not complete this request. Please retry.",
        ) from exc

    return JSONResponse(result)


def _sse(event: str, payload: dict) -> str:
    """Format one JSON Server-Sent Event without trusting message text as SSE."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_message(request: Request) -> StreamingResponse:
    """Stream buyer status and reply deltas for the interactive demo UI.

    Shopping decisions remain in ``BuyerService``.  This endpoint adds only a
    transport layer: an immediate status event, response rendering deltas, and
    a final client-safe result payload.
    """
    try:
        body = BuyerMessageRequest.model_validate(await request.json())
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Request body must contain a valid message and optional session_id.",
        ) from exc

    async def events():
        yield _sse("status", {
            "stage": "starting",
            "message": "Starting your shopping request.",
        })
        progress_events: asyncio.Queue[dict] = asyncio.Queue()
        event_loop = asyncio.get_running_loop()

        def report_progress(event: dict) -> None:
            # Graph work may later move to worker threads; schedule safely
            # back onto this response's event loop either way.
            event_loop.call_soon_threadsafe(progress_events.put_nowait, event)

        token = set_progress_reporter(report_progress)
        task = asyncio.create_task(
            buyer_service.send_message(
                message=body.message,
                session_id=body.session_id,
                buyer_id=body.buyer_id,
            )
        )
        try:
            while not task.done():
                next_progress = asyncio.create_task(progress_events.get())
                completed, _ = await asyncio.wait(
                    {task, next_progress}, return_when=asyncio.FIRST_COMPLETED,
                )
                if next_progress in completed:
                    progress = next_progress.result()
                    yield _sse(
                        str(progress.get("type", "progress")), progress
                    )
                else:
                    next_progress.cancel()
                    await asyncio.gather(next_progress, return_exceptions=True)

            while not progress_events.empty():
                progress = progress_events.get_nowait()
                yield _sse(str(progress.get("type", "progress")), progress)

            result = await task
        except ValueError as exc:
            yield _sse("error", {"detail": str(exc)})
            return
        except Exception:
            logger.exception("Streamed buyer turn failed")
            yield _sse("error", {
                "detail": "The buyer agent could not complete this request. Please retry.",
            })
            return
        finally:
            reset_progress_reporter(token)

        yield _sse("status", {
            "stage": "complete",
            "message": "Results are ready.",
        })
        reply = str(result.get("reply", ""))
        # The underlying graph uses structured calls, so these are safe UI
        # rendering deltas rather than a claim of raw model-token streaming.
        for offset in range(0, len(reply), 80):
            yield _sse("reply_delta", {"text": reply[offset:offset + 80]})
            # Keep deltas perceptible in the browser while preserving a fast
            # response for short, customer-facing summaries.
            await asyncio.sleep(0.015)
        yield _sse("complete", result)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app = Starlette(
    debug=False,
    lifespan=lifespan,
    routes=[
        Route("/", checkout_page, methods=["GET"]),
        Route("/style.css", stylesheet, methods=["GET"]),
        Route("/app.js", frontend_script, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
        Route("/v1/checkout/config", checkout_config, methods=["GET"]),
        Route("/v1/buyer/messages", send_message, methods=["POST"]),
        Route("/v1/buyer/messages/stream", stream_message, methods=["POST"]),
    ],
)
