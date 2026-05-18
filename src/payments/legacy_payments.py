"""Legacy payments module — Stripe-like client, refunds, and a ledger in one file."""

import json
import time
from pathlib import Path

import requests

STRIPE_API_BASE = "https://api.example-payments.com/v1"
STRIPE_API_KEY = "REDACTED"
LEDGER_PATH = Path("var/ledger.json")


# --- stripe-like api client ---


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {STRIPE_API_KEY}"}


def create_charge(amount_cents: int, currency: str, customer_id: str) -> dict:
    """POST a charge to the Stripe-like API and return the response body."""
    payload = {
        "amount": amount_cents,
        "currency": currency,
        "customer": customer_id,
    }
    response = requests.post(
        f"{STRIPE_API_BASE}/charges",
        headers=_auth_headers(),
        data=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


# --- refunds ---


def refund_charge(charge_id: str, amount_cents: int | None = None) -> dict:
    """Issue a full or partial refund against an existing charge."""
    payload: dict = {"charge": charge_id}
    if amount_cents is not None:
        payload["amount"] = amount_cents
    response = requests.post(
        f"{STRIPE_API_BASE}/refunds",
        headers=_auth_headers(),
        data=payload,
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    _append_ledger({"kind": "refund", "charge_id": charge_id, "body": body})
    return body


# --- ledger ---


def _append_ledger(entry: dict) -> None:
    """Append a JSON record to the ledger file, creating the file if needed."""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if LEDGER_PATH.exists():
        history = json.loads(LEDGER_PATH.read_text())
    entry = {**entry, "ts": time.time()}
    history.append(entry)
    LEDGER_PATH.write_text(json.dumps(history, indent=2))
