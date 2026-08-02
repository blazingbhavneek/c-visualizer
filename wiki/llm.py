"""OpenAI-compatible chat client with tool calling."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .config import Settings
from .http import TransportError, api_root, post_json


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class Completion:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None


class ChatClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.llm_model or ""
        self.base_url = api_root(settings.llm_base_url)
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
    ) -> Completion:
        if not self.available:
            return Completion(error="no chat endpoint configured")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = list(tools)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        try:
            response = post_json(
                f"{self.base_url}/v1/chat/completions",
                payload,
                self.settings.llm_api_key,
                self.settings.timeout_seconds,
            )
        except TransportError as exc:
            self.last_error = f"chat request failed: {exc}"
            return Completion(error=self.last_error)

        choices = response.get("choices") or []
        if not choices:
            self.last_error = "chat response had no choices"
            return Completion(error=self.last_error)

        message = choices[0].get("message") or {}
        calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            calls.append(
                ToolCall(
                    id=str(raw.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=_parse_arguments(function.get("arguments")),
                )
            )

        self.last_error = None
        return Completion(
            content=str(message.get("content") or ""),
            tool_calls=calls,
            finish_reason=str(choices[0].get("finish_reason") or ""),
            usage=response.get("usage") or {},
        )


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON *string*, and not always a valid one."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def tool(name: str, description: str, properties: dict, required: Sequence[str] = ()) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
            },
        },
    }
