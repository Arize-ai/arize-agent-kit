"""Parser for Copilot session-state transcript (events.jsonl).

The Stop hook payload supplies `transcript_path` pointing at a JSONL file with
one event per line. Each line is:

    {"type": "<kind>", "data": {...}, "id": "<uuid>",
     "timestamp": "<iso>", "parentId": "<uuid|null>"}

We extract the latest model name and a textual summary of the most recent turn
so the Stop span can carry meaningful `llm.model_name`, `input.value`, and
`output.value` attributes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_transcript(path: str | Path) -> dict[str, Any]:
    """Parse the events.jsonl at *path* and return a summary dict.

    Returns a dict with the following keys (all optional — missing keys mean
    the transcript did not provide that info):

      model_name        -- str: latest model from `session.model_change` or
                           `session.start`. Defaults to "" when absent.
      copilot_version   -- str: from `session.start.data.copilotVersion`.
      input_text        -- str: the most recent user prompt extracted from
                           `hook.start` events with hookType "userPromptSubmitted".
      output_text       -- str: best-effort assistant-turn text. Until we
                           confirm assistant-event types, this is "" — leave
                           the field present so the caller can branch on it.
      tool_count        -- int: number of `hook.start` events with hookType
                           "preToolUse".
      events_seen       -- int: total parsed events (debug aid).

    On a missing file or unreadable path, returns {} (the caller treats that as
    "no transcript data" and falls back to state-only attributes).
    """
    p = Path(path).expanduser()
    if not p.is_file():
        return {}

    summary: dict[str, Any] = {
        "model_name": "",
        "copilot_version": "",
        "input_text": "",
        "output_text": "",
        "tool_count": 0,
        "events_seen": 0,
    }

    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                summary["events_seen"] += 1
                kind = ev.get("type", "")
                data = ev.get("data") or {}

                if kind == "session.start":
                    summary["copilot_version"] = data.get("copilotVersion", "") or summary["copilot_version"]
                elif kind == "session.model_change":
                    new_model = data.get("newModel", "")
                    if new_model:
                        summary["model_name"] = new_model
                elif kind == "hook.start":
                    hook_type = data.get("hookType", "")
                    inp = data.get("input") or {}
                    if hook_type == "userPromptSubmitted":
                        prompt = inp.get("prompt", "")
                        if prompt:
                            summary["input_text"] = prompt
                    elif hook_type == "preToolUse":
                        summary["tool_count"] += 1
    except OSError:
        return {}

    return summary
