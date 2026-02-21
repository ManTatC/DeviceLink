"""
DeviceLink - Tunnel Manager
Manages WebSocket-based TCP tunnels for ADB remote screen control.
Pairs phone-side and mac-side WebSocket connections by tunnel_id,
then relays binary data between them.
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
        self._relay_tasks: list[asyncio.Task] = []

    @property
    def is_ready(self) -> bool:
        return self.phone_ws is not None and self.mac_ws is not None

    async def start_relay(self):
        """Start bidirectional binary relay between phone and mac."""
        if not self.is_ready:
            return
        logger.info(f"Tunnel [{self.tunnel_id}] relay started")
        self._relay_tasks = [
            asyncio.create_task(self._forward(self.phone_ws, self.mac_ws, "phone->mac")),
            asyncio.create_task(self._forward(self.mac_ws, self.phone_ws, "mac->phone")),
        ]
        # Wait for either direction to finish (disconnect)
        done, pending = await asyncio.wait(
            self._relay_tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        logger.info(f"Tunnel [{self.tunnel_id}] relay ended")

    async def _forward(self, src: WebSocket, dst: WebSocket, label: str):
        """Forward binary data from src to dst."""
        try:
            while True:
                data = await src.receive_bytes()
                await dst.send_bytes(data)
        except Exception as e:
            logger.info(f"Tunnel [{self.tunnel_id}] {label} closed: {type(e).__name__}")

    async def close(self):
        """Close both sides and cancel relay tasks."""
        for task in self._relay_tasks:
            task.cancel()
        for ws in [self.phone_ws, self.mac_ws]:
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass


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
