"""All Event subclasses must serialise cleanly via ``dataclasses.asdict``
+ ``json.dumps``. ``JsonlSink`` does this for every event; a future
Event with a non-JSON field would silently break the structured-log
contract without this round-trip test.
"""
from __future__ import annotations

import dataclasses
import inspect
import io
import json


from sanity_gravity import events as ev_mod
from sanity_gravity.core.reporter import JsonlSink


def _all_concrete_events():
    """Yield every concrete (non-base) Event subclass in events.py."""
    for name, obj in inspect.getmembers(ev_mod, inspect.isclass):
        if obj is ev_mod.Event:
            continue
        if not issubclass(obj, ev_mod.Event):
            continue
        # Skip imports re-exported into the module.
        if obj.__module__ != ev_mod.__name__:
            continue
        yield name, obj


def _make_event(cls):
    """Build an instance with sensible defaults for required fields."""
    base_kw = {"ts": 0.0, "run_id": "rt", "phase": None, "level": "info"}
    fields = {f.name for f in dataclasses.fields(cls)}

    extras = {}
    if "message" in fields:
        extras["message"] = "msg"
    if "argv" in fields:
        extras["argv"] = ("docker", "ps")
    if "tag" in fields:
        extras["tag"] = "ag-xfce-kasm"
    if "image" in fields:
        extras["image"] = "img"
    if "name" in fields:
        extras["name"] = "n"
    if "elapsed_s" in fields:
        extras["elapsed_s"] = 0.5
    if "connector" in fields:
        extras["connector"] = "kasm"
    if "fields" in fields:
        extras["fields"] = {"k": "v"}
    if "question" in fields:
        extras["question"] = "Proceed?"
    if "default" in fields:
        extras["default"] = "y"
    if "action_type" in fields:
        extras["action_type"] = "RunSubprocess"
    if "exit_code" in fields:
        extras["exit_code"] = 0
    if "stderr_tail" in fields:
        extras["stderr_tail"] = ""
    if "hint" in fields:
        extras["hint"] = None
    if "explain_str" in fields:
        extras["explain_str"] = ""
    if "kind" in fields:
        extras["kind"] = "subprocess"
    if "rendered" in fields:
        extras["rendered"] = "docker ps"

    return cls(**base_kw, **extras)


def test_every_event_serialises_via_jsonl_sink():
    """Run each concrete Event through JsonlSink and parse the output
    as JSON. A failure means a dataclass field can't round-trip via
    ``json.dumps(..., default=str)``."""
    buf = io.StringIO()
    sink = JsonlSink(buf)
    seen = []
    for name, cls in _all_concrete_events():
        ev = _make_event(cls)
        sink.consume(ev)
        seen.append(name)

    assert seen, "expected at least one Event subclass in events.py"
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert len(lines) == len(seen)
    for line, name in zip(lines, seen):
        payload = json.loads(line)
        assert payload["type"] == name
        assert payload["run_id"] == "rt"


def test_dataclasses_asdict_succeeds_for_every_event():
    """``dataclasses.asdict`` must succeed for every Event without
    raising — the JsonlSink relies on this conversion."""
    for name, cls in _all_concrete_events():
        ev = _make_event(cls)
        d = dataclasses.asdict(ev)
        assert "ts" in d and "run_id" in d
        # No nested object should survive un-serialised.
        json.dumps(d, default=str)
