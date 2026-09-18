"""Durable buyer memory, intentionally separate from catalog retrieval.

This module stores customer-scoped information in SQLite. It does not index
product descriptions or use embeddings: ``retrieval/`` remains the sole
semantic product-search subsystem.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class BuyerMemory:
    """SQLite-backed short-term, entity, and episodic buyer memory."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        default_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "buyer_memory.sqlite3"
        )
        self.database_path = Path(
            database_path or os.getenv("BUYER_MEMORY_DB_PATH", default_path)
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS buyer_sessions (
                    session_id TEXT PRIMARY KEY,
                    buyer_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    workflow_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_buyer_sessions_buyer
                    ON buyer_sessions (buyer_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS buyer_entities (
                    buyer_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (buyer_id, entity_type, entity_key)
                );

                CREATE TABLE IF NOT EXISTS buyer_episodes (
                    episode_id TEXT PRIMARY KEY,
                    buyer_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    outcome_type TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_buyer_episodes_buyer
                    ON buyer_episodes (buyer_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS buyer_safety_events (
                    event_id TEXT PRIMARY KEY,
                    buyer_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            connection.commit()
        finally:
            connection.close()

    def get_workflow(self, session_id: str, buyer_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT workflow_json FROM buyer_sessions
                   WHERE session_id = ? AND buyer_id = ?""",
                (session_id, buyer_id),
            ).fetchone()
        finally:
            connection.close()
        return json.loads(row["workflow_json"]) if row else None

    def get_context(self, buyer_id: str, session_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            session = connection.execute(
                """SELECT summary_json FROM buyer_sessions
                   WHERE session_id = ? AND buyer_id = ?""",
                (session_id, buyer_id),
            ).fetchone()
            entities = connection.execute(
                """SELECT entity_type, entity_key, value_json
                   FROM buyer_entities WHERE buyer_id = ?
                   ORDER BY updated_at DESC LIMIT 30""",
                (buyer_id,),
            ).fetchall()
            episodes = connection.execute(
                """SELECT outcome_type, summary_json, created_at
                   FROM buyer_episodes WHERE buyer_id = ?
                   ORDER BY created_at DESC LIMIT 3""",
                (buyer_id,),
            ).fetchall()
        finally:
            connection.close()

        preferences = {
            "preferred_brands": [],
            "constraints": [],
            "recent_products": [],
        }
        for entity in entities:
            value = json.loads(entity["value_json"])
            if entity["entity_type"] == "brand_preference":
                preferences["preferred_brands"].append(value)
            elif entity["entity_type"] == "constraint":
                preferences["constraints"].append(value)
            elif entity["entity_type"] == "product_interest":
                preferences["recent_products"].append(value)

        return {
            "session_summary": json.loads(session["summary_json"]) if session else {},
            "buyer_preferences": preferences,
            "recent_episodes": [
                {
                    "outcome_type": episode["outcome_type"],
                    "summary": json.loads(episode["summary_json"]),
                    "created_at": episode["created_at"],
                }
                for episode in episodes
            ],
        }

    def record_turn(
        self,
        buyer_id: str,
        session_id: str,
        state: dict[str, Any],
    ) -> None:
        summary = _session_summary(state)
        workflow = _workflow_snapshot(state)
        now = _utc_now()

        connection = self._connect()
        try:
            connection.execute(
                """INSERT INTO buyer_sessions
                   (session_id, buyer_id, summary_json, workflow_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     buyer_id=excluded.buyer_id,
                     summary_json=excluded.summary_json,
                     workflow_json=excluded.workflow_json,
                     updated_at=excluded.updated_at""",
                (session_id, buyer_id, _json(summary), _json(workflow), now),
            )
            self._record_entities(connection, buyer_id, state, now)

            if state.get("intent") != "general":
                connection.execute(
                    """INSERT INTO buyer_episodes
                       (episode_id, buyer_id, session_id, outcome_type, summary_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()), buyer_id, session_id,
                        _outcome_type(state), _json(summary), now,
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def record_safety_event(
        self,
        buyer_id: str,
        session_id: str,
        category: str,
    ) -> None:
        """Audit a blocked control-plane attempt without retaining its text."""
        connection = self._connect()
        try:
            connection.execute(
                """INSERT INTO buyer_safety_events
                   (event_id, buyer_id, session_id, category, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), buyer_id, session_id, category, _utc_now()),
            )
            connection.commit()
        finally:
            connection.close()

    def _record_entities(
        self,
        connection: sqlite3.Connection,
        buyer_id: str,
        state: dict[str, Any],
        now: str,
    ) -> None:
        for item in state.get("items", []):
            product = item.get("product_query")
            if product:
                self._upsert_entity(
                    connection, buyer_id, "product_interest", product.lower(), product, now,
                )
            brand = item.get("brand_preference")
            if brand:
                self._upsert_entity(
                    connection, buyer_id, "brand_preference", brand.lower(), brand, now,
                )
            for constraint in item.get("constraints") or []:
                self._upsert_entity(
                    connection, buyer_id, "constraint", constraint.lower(), constraint, now,
                )

    @staticmethod
    def _upsert_entity(
        connection: sqlite3.Connection,
        buyer_id: str,
        entity_type: str,
        entity_key: str,
        value: Any,
        now: str,
    ) -> None:
        connection.execute(
            """INSERT INTO buyer_entities
               (buyer_id, entity_type, entity_key, value_json, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(buyer_id, entity_type, entity_key) DO UPDATE SET
                 value_json=excluded.value_json, updated_at=excluded.updated_at""",
            (buyer_id, entity_type, entity_key, _json(value), now),
        )


def _session_summary(state: dict[str, Any]) -> dict[str, Any]:
    cart = state.get("cart") or {}
    return {
        "intent": state.get("intent"),
        "active_items": [
            {
                key: item.get(key)
                for key in ("product_query", "quantity", "people_count", "budget", "brand_preference", "constraints")
            }
            for item in state.get("items", [])
        ],
        "cart": {
            "items": [
                {
                    key: item.get(key)
                    for key in ("product_name", "merchant", "quantity", "total_price")
                }
                for item in cart.get("items", [])
            ],
            "total": cart.get("total", 0),
            "complete": bool(cart.get("complete")),
        },
        "awaiting_confirmation": bool(state.get("awaiting_confirmation")),
        "order_status": state.get("cart_order_status"),
    }


def _workflow_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    # This is the smallest state required to continue a pending cart safely
    # after the process restarts. Catalog hits and raw merchant prose are not
    # persisted here; they can be fetched again when needed.
    fields = (
        "intent", "conversation_action", "items", "shopping_goal", "cart",
        "cart_total", "cart_complete", "selected_offers", "validation_passed",
        "purchase_ready", "awaiting_confirmation", "user_confirmation",
        "confirmation_type", "cart_order_id", "cart_payment_status",
        "cart_order_status", "razorpay_order_id", "razorpay_payment_id",
        "razorpay_signature", "razorpay_payment_verified",
    )
    return {field: state.get(field) for field in fields if field in state}


def _outcome_type(state: dict[str, Any]) -> str:
    if state.get("cart_order_id"):
        return "payment_order_created"
    if state.get("awaiting_confirmation"):
        return "purchase_confirmation_requested"
    if state.get("cart_complete"):
        return "recommendation_prepared"
    return "no_matching_offer"
