"""model provider interface. agents only talk to `Provider.chat`, so swapping models
or replaying canned responses in tests doesn't touch any agent code."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .config import PRICES

API_URL = "https://api.anthropic.com/v1/messages"


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    by_agent: dict = field(default_factory=dict)

    def add(self, agent: str, inp: int, out: int) -> None:
        self.input_tokens += inp
        self.output_tokens += out
        self.calls += 1
        a = self.by_agent.setdefault(agent, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
        a["input_tokens"] += inp
        a["output_tokens"] += out
        a["calls"] += 1

    def cost(self, model: str) -> float:
        pin, pout = PRICES.get(model, (0.0, 0.0))
        return round(self.input_tokens / 1e6 * pin + self.output_tokens / 1e6 * pout, 4)

    def to_dict(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "calls": self.calls, "by_agent": self.by_agent}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Usage":
        d = d or {}
        return cls(d.get("input_tokens", 0), d.get("output_tokens", 0), d.get("calls", 0), d.get("by_agent", {}))


class Provider:
    model: str = "unknown"

    def chat(self, system: str, messages: list, tools: list, tool_choice: dict | None = None,
             max_tokens: int = 4096) -> dict:
        raise NotImplementedError


class AnthropicProvider(Provider):
    """plain https call to the messages api, no sdk needed."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is missing. put it in the .env file in the mobileforge folder.")
        self.api_key = api_key
        self.model = model

    def chat(self, system, messages, tools, tool_choice=None, max_tokens=4096):
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": messages, "tools": tools}
        if tool_choice:
            body["tool_choice"] = tool_choice
        data = json.dumps(body).encode("utf-8")

        # retry rate limits and overloads with backoff, fail fast on everything else
        for attempt in range(6):
            req = urllib.request.Request(API_URL, data=data, method="POST", headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=300) as res:
                    return json.loads(res.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code == 400 and "signature" in detail and "thinking" in detail and not body.get("_stripped"):
                    # old thinking blocks can't be verified anymore, drop them and try again
                    body["messages"] = strip_thinking(messages)
                    body["_stripped"] = True
                    data = json.dumps({k: v for k, v in body.items() if k != "_stripped"}).encode("utf-8")
                    continue
                if e.code in (429, 500, 502, 503, 529) and attempt < 5:
                    time.sleep(min(60, 2 ** attempt * 3))
                    continue
                raise LLMError(f"anthropic api error {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                if attempt < 5:
                    time.sleep(3)
                    continue
                raise LLMError(f"couldn't reach the anthropic api: {e.reason}") from e
        raise LLMError("anthropic api kept failing")


def strip_thinking(messages: list) -> list:
    out = []
    for m in messages:
        if m["role"] == "assistant" and isinstance(m["content"], list):
            kept = [b for b in m["content"] if b.get("type") not in ("thinking", "redacted_thinking")]
            out.append({**m, "content": kept or [{"type": "text", "text": "(thinking omitted)"}]})
        else:
            out.append(m)
    return out


class ScriptedProvider(Provider):
    """replays canned responses. used by the unit tests so they run free and offline."""

    model = "scripted"

    def __init__(self, script):
        # script is a list of responses, or a function(system, messages, tools) -> response
        self.script = script
        self.seen: list = []

    def chat(self, system, messages, tools, tool_choice=None, max_tokens=4096):
        self.seen.append({"system": system, "messages": json.loads(json.dumps(messages)), "tools": tools})
        if callable(self.script):
            return self.script(system, messages, tools)
        if not self.script:
            raise LLMError("scripted provider ran out of responses")
        return self.script.pop(0)


def tool_call(name: str, args: dict, call_id: str | None = None, text: str = "") -> dict:
    # helper for building fake responses in tests
    content = [{"type": "text", "text": text}] if text else []
    content.append({"type": "tool_use", "id": call_id or f"call_{name}_{time.time_ns()}", "name": name, "input": args})
    return {"content": content, "stop_reason": "tool_use", "usage": {"input_tokens": 100, "output_tokens": 20}}


def make_provider(settings) -> Provider:
    return AnthropicProvider(settings.api_key, settings.model)
