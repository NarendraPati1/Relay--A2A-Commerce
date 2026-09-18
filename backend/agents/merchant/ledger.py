"""Durable merchant transaction and audit storage.

This local SQLite implementation is deliberately behind a small interface so
production can replace it with a merchant-owned transactional database.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MerchantLedger:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS merchant_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    buyer_reference TEXT,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payment_order_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (merchant_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS merchant_audit_events (
                    event_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    transaction_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def record_event(
        self,
        merchant_id: str,
        event_type: str,
        payload: dict[str, Any],
        transaction_id: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO merchant_audit_events
                   (event_id, merchant_id, transaction_id, event_type, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), merchant_id, transaction_id, event_type,
                    json.dumps(payload, sort_keys=True), _now(),
                ),
            )

    def create_pending_transaction(
        self,
        *,
        merchant_id: str,
        idempotency_key: str,
        buyer_reference: str | None,
        product_name: str,
        quantity: int,
        unit_price: float,
    ) -> tuple[dict[str, Any], bool]:
        """Create once per merchant idempotency key and return (record, new)."""
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """SELECT * FROM merchant_transactions
                   WHERE merchant_id = ? AND idempotency_key = ?""",
                (merchant_id, idempotency_key),
            ).fetchone()
            if existing:
                return dict(existing), False

            transaction_id = str(uuid.uuid4())
            timestamp = _now()
            total_amount = round(unit_price * quantity, 2)
            connection.execute(
                """INSERT INTO merchant_transactions
                   (transaction_id, merchant_id, idempotency_key, buyer_reference,
                    product_name, quantity, unit_price, total_amount, currency,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'INR', 'payment_pending', ?, ?)""",
                (
                    transaction_id, merchant_id, idempotency_key, buyer_reference,
                    product_name, quantity, unit_price, total_amount, timestamp,
                    timestamp,
                ),
            )
            record = dict(connection.execute(
                "SELECT * FROM merchant_transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone())
            return record, True

    def attach_payment_order(
        self, transaction_id: str, payment_order_id: str,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE merchant_transactions
                   SET payment_order_id = ?, updated_at = ?
                   WHERE transaction_id = ?""",
                (payment_order_id, _now(), transaction_id),
            )

    def transaction_for_payment_order(
        self, merchant_id: str, payment_order_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM merchant_transactions
                   WHERE merchant_id = ? AND payment_order_id = ?""",
                (merchant_id, payment_order_id),
            ).fetchone()
            return dict(row) if row else None

    def mark_payment_verified(
        self,
        *,
        transaction_id: str,
        payment_id: str,
        verification_source: str,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE merchant_transactions
                   SET status = 'paid', updated_at = ?
                   WHERE transaction_id = ? AND status = 'payment_pending'""",
                (_now(), transaction_id),
            )
        self.record_event(
            merchant_id=self._merchant_id_for(transaction_id),
            transaction_id=transaction_id,
            event_type="payment_verified",
            payload={"payment_id": payment_id, "source": verification_source},
        )

    def _merchant_id_for(self, transaction_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT merchant_id FROM merchant_transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        if not row:
            raise ValueError("Unknown merchant transaction.")
        return str(row["merchant_id"])

    def events(self, merchant_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT * FROM merchant_audit_events WHERE merchant_id = ?
                   ORDER BY created_at""",
                (merchant_id,),
            )]
