"""LLM providers behind one tiny interface (PLAN §6.7, §11).

Conversation state is kept in a provider-neutral form:
  {"role": "user", "content": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "results": [{"id", "name", "content": str}]}
Each provider converts that to its own wire format. The conversion functions are pure so they can be tested
without network access or API keys.

Live calls (AnthropicProvider, OpenAICompatProvider) have NOT been exercised against a real API yet: no key was
available when this was written. Treat them as untested until a first real run.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ProviderReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    def to_json(self) -> dict:
        return {"text": self.text, "tool_calls": [vars(t) for t in self.tool_calls],
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    @classmethod
    def from_json(cls, d: dict) -> "ProviderReply":
        return cls(d.get("text", ""), [ToolCall(**t) for t in d.get("tool_calls", [])],
                   d.get("input_tokens", 0), d.get("output_tokens", 0))


class Provider(Protocol):
    name: str

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ProviderReply: ...


class ProviderError(Exception):
    pass


# ----------------------------------------------------------------------------- wire-format conversion

def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks = []
            if m.get("text"):
                blocks.append({"type": "text", "text": m["text"]})
            blocks += [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["args"]}
                       for t in m.get("tool_calls", [])]
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no output)"}]})
        elif m["role"] == "tool":
            out.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]} for r in m["results"]]})
    return out


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("text") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [{"id": t["id"], "type": "function",
                                      "function": {"name": t["name"], "arguments": json.dumps(t["args"])}}
                                     for t in m["tool_calls"]]
            out.append(msg)
        elif m["role"] == "tool":
            out += [{"role": "tool", "tool_call_id": r["id"], "content": r["content"]} for r in m["results"]]
    return out


def parse_openai_response(body: dict) -> ProviderReply:
    try:
        msg = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"unexpected response shape: {str(body)[:200]}") from e
    calls = []
    for tc in msg.get("tool_calls") or []:
        raw = tc["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = {"_unparsed": raw}  # surfaced to the agent as a tool error rather than crashing the run
        calls.append(ToolCall(tc.get("id") or f"call_{len(calls)}", tc["function"]["name"], args))
    u = body.get("usage") or {}
    return ProviderReply(msg.get("content") or "", calls, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


# ----------------------------------------------------------------------------- live providers

class AnthropicProvider:
    """Anthropic Messages API with tool use. Requires `pip install anthropic` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str, max_tokens: int = 1024, temperature: float | None = 0.0):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - depends on environment
            raise ProviderError("pip install 'dia[llm]' to use the Anthropic provider") from e
        self.name = f"anthropic:{model}"
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY (and optional base URL) from the environment

    def complete(self, system, messages, tools):  # pragma: no cover - needs network + key
        kw = {"temperature": self.temperature} if self.temperature is not None else {}
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=to_anthropic_messages(messages),
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                   for t in tools], **kw)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return ProviderReply(text, calls, resp.usage.input_tokens, resp.usage.output_tokens)


class OpenAICompatProvider:
    """Any OpenAI-compatible /chat/completions endpoint (OpenAI, OpenRouter, Groq, Ollama, vLLM).

    Env: OPENAI_API_KEY (optional for local servers), OPENAI_BASE_URL (default https://api.openai.com/v1).
    Standard library only, so no extra dependency.
    """

    def __init__(self, model: str, base_url: str | None = None, temperature: float | None = 0.0,
                 timeout: float = 120.0, retries: int = 3):
        self.name = f"openai:{model}"
        self.model, self.temperature, self.timeout, self.retries = model, temperature, timeout, retries
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.key = os.environ.get("OPENAI_API_KEY", "")

    def complete(self, system, messages, tools):  # pragma: no cover - needs network
        body = {"model": self.model, "messages": to_openai_messages(system, messages),
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                            "parameters": t["input_schema"]}} for t in tools]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return parse_openai_response(json.loads(r.read()))
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise ProviderError(f"HTTP {e.code}: {e.read()[:200]!r}") from e
            except urllib.error.URLError as e:
                if attempt < self.retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise ProviderError(f"network error: {e}") from e
        raise ProviderError("retries exhausted")


# ----------------------------------------------------------------------------- record / replay

class ReplayProvider:
    """Replays recorded assistant turns, so a run can be reproduced exactly with no model access."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.name = f"replay:{self.dir.name}"
        self._replies: list[ProviderReply] = []

    def begin(self, key: str) -> None:
        p = self.dir / f"{key}.json"
        if not p.exists():
            raise ProviderError(f"no recorded transcript for scenario key {key} in {self.dir}")
        self._replies = [ProviderReply.from_json(r) for r in json.loads(p.read_text())["replies"]]

    def complete(self, system, messages, tools):
        if not self._replies:
            raise ProviderError("replay exhausted: the run diverged from the recording")
        return self._replies.pop(0)


def save_transcript(directory: str | Path, key: str, replies: list[ProviderReply], meta: dict) -> None:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps({"meta": meta, "replies": [r.to_json() for r in replies]}, indent=1))
