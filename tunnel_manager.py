"""
DeviceLink - Tunnel Manager (v3 - Multiplexed)
Pairs two WebSocket connections by tunnel_id.
Purely forwards binary data - clients handle mux/demux.
"""

import asyncio
import logging
from fastapi import WebSocket

logger = logging.getLogger("devicelink.tunnel")


class TunnelPair:
    def __init__(self, tunnel_id: str):
        self.tunnel_id = tunnel_id
        self.ws_a: WebSocket | None = None
        self.ws_b: WebSocket | None = None
        self.ready_event = asyncio.Event()

    @property
    def is_ready(self) -> bool:
        return self.ws_a is not None and self.ws_b is not None

    def add_ws(self, ws: WebSocket) -> str:
        """Add a WebSocket, returns 'a' or 'b'."""
        if self.ws_a is None:
            self.ws_a = ws
            return "a"
        else:
            self.ws_b = ws
            return "b"

    def get_peer(self, side: str) -> WebSocket | None:
        return self.ws_b if side == "a" else self.ws_a


class TunnelManager:
    def __init__(self):
        self._tunnels: dict[str, TunnelPair] = {}

    def get_or_create(self, tunnel_id: str) -> TunnelPair:
        if tunnel_id not in self._tunnels:
            self._tunnels[tunnel_id] = TunnelPair(tunnel_id)
        return self._tunnels[tunnel_id]

    def remove(self, tunnel_id: str):
        self._tunnels.pop(tunnel_id, None)

    def list_tunnels(self) -> list[dict]:
        return [
            {"tunnel_id": tid, "sides": (1 if p.ws_a else 0) + (1 if p.ws_b else 0), "ready": p.is_ready}
            for tid, p in self._tunnels.items()
        ]


tunnel_manager = TunnelManager()
