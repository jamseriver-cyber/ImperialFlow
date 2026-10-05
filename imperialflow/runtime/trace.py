import json
from datetime import datetime, timezone, timedelta

from .evidence import digest


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def seal_event(event):
    return {**event, "event_sha256": digest(canonical_json(event).encode("utf-8"))}
