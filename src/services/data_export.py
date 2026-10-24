"""Personal data export (GDPR art. 15 / 20, India DPDP Act s. 11): everything
the app stores about one user, as a single JSON document.

Walks the same tables account deletion does (every table with a ``user_id``
pointing at users, plus their child tables such as holdings, transactions and
watchlist items), so a table added later is exported without changes here.
Credentials are never exported: password and 2FA secrets, session and
one-time token hashes, encrypted API keys and push-subscription keys are left
out (see REDACT).
"""

from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ..core import tenant
from ..storage import Base

# table -> columns never exported (secrets or security tokens, not personal data
# a person can use). Tables in SKIP_TABLES are left out entirely.
REDACT = {
    "user_api_keys": {"key_ciphertext"},
    "report_runs": {"token"},
    "web_push_subscriptions": {"p256dh", "auth"},
}
SKIP_TABLES: set[str] = set()
FORMAT_VERSION = 1


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode()
    return value


def _rows(session: Session, table, where) -> list[dict]:
    hidden = REDACT.get(table.name, set())
    cols = [c for c in table.columns if c.name not in hidden]
    return [{c.name: _plain(row._mapping[c.name]) for c in cols}
            for row in session.execute(table.select().where(where))]


def export_user(session: Session, user_id: int) -> dict:
    """{"tables": {table: [rows]}} for one user, credentials removed."""
    tables: dict[str, list[dict]] = {}
    with tenant.system_scope():
        users = Base.metadata.tables["users"]
        tables["users"] = _rows(session, users, users.c.id == user_id)
        owned: dict[str, list] = {}
        for table in Base.metadata.sorted_tables:
            col = table.columns.get("user_id")
            if col is None or table.name in SKIP_TABLES or table.name == "users":
                continue
            if not any(f.column.table.name == "users" for f in col.foreign_keys):
                continue
            rows = _rows(session, table, col == user_id)
            tables[table.name] = rows
            if "id" in table.columns:
                owned[table.name] = [r["id"] for r in rows if r.get("id") is not None]
        # Child tables: rows that point at something the user owns (holdings,
        # transactions, watchlist items) but carry no user_id of their own.
        for table in Base.metadata.sorted_tables:
            if table.name in tables or table.name in SKIP_TABLES or "user_id" in table.columns:
                continue
            for col in table.columns:
                parent = next((f.column.table.name for f in col.foreign_keys if f.column.table.name in owned), None)
                if parent and owned[parent]:
                    tables[table.name] = _rows(session, table, col.in_(owned[parent]))
                    break
    return {
        "format": "marketmyna-personal-data",
        "version": FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "user_id": user_id,
        "notes": [
            "Everything MarketMyna stores about your account, one list per table.",
            "Left out on purpose: your password and 2-factor secrets, login and email-link tokens, "
            "your saved AI keys and webhook links (stored encrypted) "
            "and the keys of your browser push subscriptions.",
            "Market data (prices, fund NAVs, listings) is public data, not personal data, and is not included.",
        ],
        "tables": {k: v for k, v in tables.items() if v},
    }
