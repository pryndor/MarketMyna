"""Read a JSON object out of a model's reply, tolerating the usual damage:
code fences, prose around the object, and a reply cut off at the token
limit (reasoning models spend part of the budget thinking). A cut-off
object is closed after its last complete value, so finished fields
survive and the half-written one is dropped."""

from __future__ import annotations

import json
from typing import Optional


def parse_object(text: str) -> Optional[dict]:
    start = (text or "").find("{")
    if start < 0:
        return None
    body = text[start:]
    end = body.rfind("}")
    if end >= 0:
        try:
            data = json.loads(body[: end + 1])
            return data if isinstance(data, dict) else None
        except ValueError:
            pass
    return _close_truncated(body)


def _close_truncated(body: str) -> Optional[dict]:
    """Cut at the last point where a value had just finished (a ',' outside
    any string), then add the closing brackets that are still open."""
    stack: list[str] = []
    in_string = escaped = False
    cut: Optional[tuple[int, list[str]]] = None
    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if not stack:
                return None  # a complete object that still failed to parse: not truncation
            cut = (i + 1, list(stack))
        elif ch == ",":
            cut = (i, list(stack))
    if cut is None:
        return None
    pos, open_ = cut
    try:
        data = json.loads(body[:pos] + "".join(reversed(open_)))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
