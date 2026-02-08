"""
DeviceLink - WebSocket Connection Manager
Manages real-time WebSocket connections for all devices.
"""

from fastapi import WebSocket
from datetime import datetime, timezone
import json
import logging

logger = logging.getLogger("devicelink")


class ConnectionManager:
    """Manages WebSocket connections for all devices."""

    def __init__(self):
        # device_id -> WebSocket
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, device_id: str, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        # Close existing connection if device reconnects
        if device_id in self.active_connections:
            try:
                await self.active_connections[device_id].close()
            except Exception:
                pass
        self.active_connections[device_id] = websocket
        logger.info(f"Device connected: {device_id}")

    def disconnect(self, device_id: str):
        """Remove a device's WebSocket connection."""
        if device_id in self.active_connections:
            del self.active_connections[device_id]
            logger.info(f"Device disconnected: {device_id}")

    def is_online(self, device_id: str) -> bool:
        """Check if a device has an active WebSocket connection."""
        return device_id in self.active_connections

    def get_online_device_ids(self) -> list[str]:
        """Return list of currently connected device IDs."""
        return list(self.active_connections.keys())

    async def send_to_device(self, device_id: str, message: dict):
        """Send a JSON message to a specific device."""
        if device_id in self.active_connections:
            try:
                await self.active_connections[device_id].send_json(message)
            except Exception as e:
                logger.error(f"Failed to send to {device_id}: {e}")
                self.disconnect(device_id)

    async def broadcast(self, message: dict, exclude_device: str = None):
        """Broadcast a JSON message to all connected devices."""
        disconnected = []
        for device_id, ws in self.active_connections.items():
            if device_id == exclude_device:
                continue
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Broadcast failed for {device_id}: {e}")
                disconnected.append(device_id)

        for device_id in disconnected:
            self.disconnect(device_id)

    async def broadcast_clipboard(self, device_id: str, device_name: str, content: str, content_type: str = "text"):
        """Broadcast a clipboard update to all other devices."""
        await self.broadcast(
            {
                "type": "clipboard_update",
                "device_id": device_id,
                "device_name": device_name,
                "content": content,
                "content_type": content_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            exclude_device=device_id,
        )

    async def broadcast_device_status(self, device_id: str, status: dict):
        """Broadcast device status update to all connected clients (including web dashboard)."""
        await self.broadcast(
            {
                "type": "device_status",
                "device_id": device_id,
                **status,
            }
        )


# Singleton instance
manager = ConnectionManager()
