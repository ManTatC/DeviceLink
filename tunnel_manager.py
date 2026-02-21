"""
DeviceLink - Tunnel Manager
Manages WebSocket-based TCP tunnels for ADB remote screen control.
Pairs phone-side and mac-side WebSocket connections by tunnel_id.
Each handler forwards messages from its own WS to the peer's WS.
"""

import asyncio
import logging
from fastapi import WebSocket

logger = logging.getLogger("devicelink.tunnel")


class TunnelPair:
    """A pair of WebSocket connections (phone + mac) for one tunnel."""

    def __init__(self, tunnel_id: str):
        self.tunnel_id = tunnel_id
        self.phone_ws: WebSocket | None = None
        self.mac_ws: WebSocket | None = None
        self.ready_event = asyncio.Event()

    @property
    def is_ready(self) -> bool:
        return self.phone_ws is not None and self.mac_ws is not None

    def get_peer_ws(self, role: str) -> WebSocket | None:
        """Get the peer's WebSocket for a given role."""
        if role == "phone":
            return self.mac_ws
        return self.phone_ws


class TunnelManager:
    """Manages all active tunnels."""

    def __init__(self):
        self._tunnels: dict[str, TunnelPair] = {}

    def get_or_create(self, tunnel_id: str) -> TunnelPair:
        if tunnel_id not in self._tunnels:
            self._tunnels[tunnel_id] = TunnelPair(tunnel_id)
        return self._tunnels[tunnel_id]

    def remove(self, tunnel_id: str):
        self._tunnels.pop(tunnel_id, None)

    def list_tunnels(self) -> list[dict]:
        result = []
        for tid, pair in self._tunnels.items():
            result.append({
                "tunnel_id": tid,
                "phone_connected": pair.phone_ws is not None,
                "mac_connected": pair.mac_ws is not None,
                "relaying": pair.is_ready,
            })
        return result


# Global singleton
tunnel_manager = TunnelManager()
