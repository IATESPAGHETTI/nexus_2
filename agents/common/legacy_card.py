"""Let an A2A 0.3 client (CrewAI's pinned a2a-sdk) read the agent card of an ADK service.

ADK 2.9 serves an A2A 1.0 card: the endpoint is only inside `supportedInterfaces`. The 0.3 `AgentCard` requires top-level
`url`, `protocolVersion` and `preferredTransport`, so a 0.3 client rejects the card before it sends anything. This ASGI
middleware adds those three fields to the card JSON. Both parsers accept the result (a 1.x parser ignores them, a 0.3 parser
ignores `supportedInterfaces`). The JSON-RPC route already accepts 0.3 requests (`enable_v0_3_compat=True`, ADK's default).
"""

from __future__ import annotations

import json

CARD_PATH = "/.well-known/agent-card.json"


def add_legacy_fields(card: dict) -> dict:
    """Return the card with the A2A 0.3 top-level fields added. Never overrides a field the card already has."""
    interfaces = card.get("supportedInterfaces") or []
    if not interfaces or "url" in card:
        return card
    out = dict(card)
    out["url"] = interfaces[0].get("url", "")
    out.setdefault("protocolVersion", "0.3.0")
    out.setdefault("preferredTransport", "JSONRPC")
    return out


class LegacyCardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "GET" or scope.get("path") != CARD_PATH:
            await self.app(scope, receive, send)
            return
        start, body = {}, bytearray()

        async def capture(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if message.get("more_body"):
                    return
                data = bytes(body)
                try:
                    data = json.dumps(add_legacy_fields(json.loads(data))).encode()
                except ValueError:
                    pass                      # not JSON (an error page): pass it through unchanged
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(data)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": data})

        await self.app(scope, receive, capture)
