"""Gemini provider — calls Google's Generative Language API via httpx."""

import json
import logging
import uuid
from typing import Any

import httpx

from .base import Message, Provider, ToolCall

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(Provider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=120)

    @property
    def name(self) -> str:
        return "gemini"

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> Message:
        url = f"{GEMINI_API_URL}/{self.model}:generateContent"

        # Build Gemini request body
        system_text, contents = self._build_contents(messages)
        body: dict[str, Any] = {"contents": contents}

        if system_text:
            body["system_instruction"] = {"parts": [{"text": system_text}]}

        if tools:
            body["tools"] = [{"function_declarations": self._convert_tools(tools)}]

        logger.debug("Gemini request: %d messages, %d tools", len(contents), len(tools or []))

        resp = await self._client.post(
            url,
            json=body,
            headers={"x-goog-api-key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    def _build_contents(self, messages: list[Message]) -> tuple[str, list[dict]]:
        """Convert our Message format to Gemini's contents format.

        Returns (system_text, contents) — system text is passed via the
        system_instruction API field, not injected into user messages.
        """
        contents: list[dict] = []
        system_parts: list[str] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
                continue

            if msg.role == "tool":
                # Tool results go as function response parts
                contents.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.name,
                            "response": {"result": msg.content},
                        }
                    }],
                })
                continue

            role = "user" if msg.role == "user" else "model"
            parts: list[dict] = []

            # Ignore raw_content (Claude-specific server-side tool blocks)
            if msg.content:
                parts.append({"text": msg.content})

            for tc in msg.tool_calls:
                parts.append({
                    "functionCall": {
                        "name": tc.name,
                        "args": tc.arguments,
                    }
                })

            if parts:
                contents.append({"role": role, "parts": parts})

        system_text = "\n\n".join(system_parts).strip()
        return system_text, contents

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-style tool defs to Gemini function declarations."""
        declarations = []
        for tool in tools:
            func = tool.get("function", tool)
            decl: dict[str, Any] = {
                "name": func["name"],
                "description": func.get("description", ""),
            }
            params = func.get("parameters")
            if params:
                decl["parameters"] = params
            declarations.append(decl)
        return declarations

    def _parse_response(self, data: dict) -> Message:
        """Parse Gemini response into our Message format."""
        candidates = data.get("candidates", [])
        if not candidates:
            return Message(role="assistant", content="(No response from Gemini)")

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(ToolCall(
                    id=str(uuid.uuid4()),
                    name=fc["name"],
                    arguments=fc.get("args", {}),
                ))

        return Message(
            role="assistant",
            content="\n".join(text_parts),
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        await self._client.aclose()
