from __future__ import annotations

from typing import Any

from a2a.helpers.proto_helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from agents.merchant.commerce import MerchantCommerceService


class MerchantAgentExecutor(AgentExecutor):
    def __init__(
        self,
        merchant_config: dict[str, Any],
        service: MerchantCommerceService | None = None,
    ):
        self.service = service or MerchantCommerceService(
            merchant_id=merchant_config["id"],
            merchant_name=merchant_config["name"],
            inventory=merchant_config["inventory"],
            discount_rules=merchant_config.get("discount_rules", []),
            recommendation_policy=merchant_config.get("recommendation_policy", {}),
        )

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        if context.current_task:
            task = context.current_task
        else:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )

        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Merchant Agent is checking inventory."),
        )

        request_text = get_message_text(context.message)
        response = self.service.handle_request(request_text)

        await updater.add_artifact(
            parts=[new_text_part(text=response, media_type="text/plain")]
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Merchant Agent completed the request."),
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        return None
