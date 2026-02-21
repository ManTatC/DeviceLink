"""
DeviceLink - Main Server Application
FastAPI backend with REST API + WebSocket for device interconnection.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional
import json
import logging
import os
import asyncio

from models import Device, ClipboardEntry, init_db, get_db
from ws_manager import manager
from tunnel_manager import tunnel_manager

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("devicelink")

# Init
app = FastAPI(title="DeviceLink", version="1.0.0")

# CORS — allow all origins for device agents
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Schemas ───

class DeviceRegister(BaseModel):
    device_id: str
    name: str
    device_type: str = "other"  # mac, phone, tablet, other
    os: Optional[str] = None


class DeviceHeartbeat(BaseModel):
    device_id: str
    ip: Optional[str] = None
    battery: Optional[int] = None
    storage_total: Optional[float] = None
    storage_free: Optional[float] = None


class ClipboardCreate(BaseModel):
    device_id: str
    content: str
    content_type: str = "text"


# ─── Lifecycle ───

@app.on_event("startup")
async def startup():
    init_db()
    logger.info("DeviceLink server started")


# ─── REST API: Devices ───

@app.post("/api/devices/register")
async def register_device(data: DeviceRegister, db: Session = Depends(get_db)):
    """Register a new device or update existing one."""
    device = db.query(Device).filter(Device.id == data.device_id).first()
    if device:
        device.name = data.name
        device.device_type = data.device_type
        device.os = data.os
        device.last_seen = datetime.now(timezone.utc)
    else:
        device = Device(
            id=data.device_id,
            name=data.name,
            device_type=data.device_type,
            os=data.os,
        )
        db.add(device)
    db.commit()
    db.refresh(device)
    return {"status": "ok", "device_id": device.id}


@app.get("/api/devices")
async def list_devices(db: Session = Depends(get_db)):
    """List all registered devices with online status."""
    devices = db.query(Device).filter(
        ~Device.id.startswith("dashboard-")
    ).order_by(Device.last_seen.desc()).all()
    online_ids = manager.get_online_device_ids()
    result = []
    for d in devices:
        result.append({
            "id": d.id,
            "name": d.name,
            "device_type": d.device_type,
            "os": d.os,
            "ip": d.ip,
            "battery": d.battery,
            "storage_total": d.storage_total,
            "storage_free": d.storage_free,
            "online": d.id in online_ids,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        })
    return {"devices": result}


@app.post("/api/devices/heartbeat")
async def device_heartbeat(data: DeviceHeartbeat, db: Session = Depends(get_db)):
    """Update device status (battery, storage, etc.)."""
    device = db.query(Device).filter(Device.id == data.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.last_seen = datetime.now(timezone.utc)
    if data.ip is not None:
        device.ip = data.ip
    if data.battery is not None:
        device.battery = data.battery
    if data.storage_total is not None:
        device.storage_total = data.storage_total
    if data.storage_free is not None:
        device.storage_free = data.storage_free
    db.commit()

    # Broadcast status to all WebSocket clients
    await manager.broadcast_device_status(data.device_id, {
        "name": device.name,
        "device_type": device.device_type,
        "battery": device.battery,
        "storage_total": device.storage_total,
        "storage_free": device.storage_free,
        "online": True,
        "last_seen": device.last_seen.isoformat(),
    })

    return {"status": "ok"}


@app.delete("/api/devices/{device_id}")
async def remove_device(device_id: str, db: Session = Depends(get_db)):
    """Remove a device."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return {"status": "ok"}


# ─── REST API: Clipboard ───

@app.post("/api/clipboard")
async def push_clipboard(data: ClipboardCreate, db: Session = Depends(get_db)):
    """Push clipboard content from a device."""
    device = db.query(Device).filter(Device.id == data.device_id).first()
    device_name = device.name if device else "Unknown"

    entry = ClipboardEntry(
        device_id=data.device_id,
        device_name=device_name,
        content=data.content,
        content_type=data.content_type,
    )
    db.add(entry)
    db.commit()

    # Broadcast to all other devices
    await manager.broadcast_clipboard(
        data.device_id, device_name, data.content, data.content_type
    )

    return {"status": "ok", "id": entry.id}


@app.get("/api/clipboard")
async def get_clipboard_history(limit: int = 50, db: Session = Depends(get_db)):
    """Get recent clipboard entries."""
    entries = (
        db.query(ClipboardEntry)
        .order_by(ClipboardEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "entries": [
            {
                "id": e.id,
                "device_id": e.device_id,
                "device_name": e.device_name,
                "content": e.content,
                "content_type": e.content_type,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ]
    }


@app.delete("/api/clipboard/{entry_id}")
async def delete_clipboard_entry(entry_id: str, db: Session = Depends(get_db)):
    """Delete a clipboard entry."""
    entry = db.query(ClipboardEntry).filter(ClipboardEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"status": "ok"}


# ─── WebSocket ───

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str, db: Session = Depends(get_db)):
    """WebSocket connection for real-time device communication."""
    await manager.connect(device_id, websocket)

    # Update device last_seen
    device = db.query(Device).filter(Device.id == device_id).first()
    if device:
        device.last_seen = datetime.now(timezone.utc)
        db.commit()

    # Broadcast that device came online
    await manager.broadcast({
        "type": "device_online",
        "device_id": device_id,
        "name": device.name if device else device_id,
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "heartbeat":
                # Update device status
                if device:
                    device.last_seen = datetime.now(timezone.utc)
                    if "battery" in data:
                        device.battery = data["battery"]
                    if "storage_total" in data:
                        device.storage_total = data["storage_total"]
                    if "storage_free" in data:
                        device.storage_free = data["storage_free"]
                    if "ip" in data:
                        device.ip = data["ip"]
                    db.commit()

                    await manager.broadcast_device_status(device_id, {
                        "name": device.name,
                        "device_type": device.device_type,
                        "battery": device.battery,
                        "storage_total": device.storage_total,
                        "storage_free": device.storage_free,
                        "online": True,
                        "last_seen": device.last_seen.isoformat(),
                    })

            elif msg_type == "clipboard":
                # Device pushed clipboard content
                content = data.get("content", "")
                content_type = data.get("content_type", "text")
                device_name = device.name if device else device_id

                entry = ClipboardEntry(
                    device_id=device_id,
                    device_name=device_name,
                    content=content,
                    content_type=content_type,
                )
                db.add(entry)
                db.commit()

                await manager.broadcast_clipboard(
                    device_id, device_name, content, content_type
                )

            elif msg_type == "ping":
                await manager.send_to_device(device_id, {"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(device_id)
        await manager.broadcast({
            "type": "device_offline",
            "device_id": device_id,
            "name": device.name if device else device_id,
        })
    except Exception as e:
        logger.error(f"WebSocket error for {device_id}: {e}")
        manager.disconnect(device_id)


# ─── ADB Tunnel (Remote Screen Control) ───

@app.websocket("/ws/tunnel/{tunnel_id}/{role}")
async def tunnel_endpoint(websocket: WebSocket, tunnel_id: str, role: str):
    """
    WebSocket tunnel for ADB remote screen control.
    Each handler reads from its own WS and forwards to the peer's WS.
    """
    if role not in ("phone", "mac"):
        await websocket.close(code=4000, reason="Role must be 'phone' or 'mac'")
        return

    await websocket.accept()
    pair = tunnel_manager.get_or_create(tunnel_id)

    if role == "phone":
        pair.phone_ws = websocket
        logger.info(f"Tunnel [{tunnel_id}] phone connected")
    else:
        pair.mac_ws = websocket
        logger.info(f"Tunnel [{tunnel_id}] mac connected")

    # If both sides connected, signal ready
    if pair.is_ready:
        pair.ready_event.set()

    # Notify this side
    try:
        await websocket.send_json({
            "type": "status",
            "message": f"{role} connected, {'tunnel active, starting relay' if pair.is_ready else 'waiting for peer...'}"
        })
    except Exception:
        pass

    # Wait for peer (up to 5 minutes)
    try:
        await asyncio.wait_for(pair.ready_event.wait(), timeout=300)
    except asyncio.TimeoutError:
        logger.info(f"Tunnel [{tunnel_id}] {role} timed out")
        tunnel_manager.remove(tunnel_id)
        return

    # Send relay-start signal
    try:
        await websocket.send_json({"type": "status", "message": "tunnel active, starting relay"})
    except Exception:
        pass

    # Forward: read from MY websocket, write to PEER's websocket
    peer_ws = pair.get_peer_ws(role)
    if not peer_ws:
        return

    logger.info(f"Tunnel [{tunnel_id}] {role} relay started")
    try:
        while True:
            message = await websocket.receive()
            msg_type = message.get("type", "")
            if msg_type == "websocket.receive":
                if message.get("bytes"):
                    await peer_ws.send_bytes(message["bytes"])
                elif message.get("text"):
                    await peer_ws.send_text(message["text"])
            elif msg_type == "websocket.disconnect":
                break
    except Exception as e:
        logger.info(f"Tunnel [{tunnel_id}] {role} ended: {type(e).__name__}")
    finally:
        tunnel_manager.remove(tunnel_id)
        # Try to close peer
        try:
            await peer_ws.close()
        except Exception:
            pass


@app.get("/api/tunnels")
async def list_tunnels():
    """List active tunnels."""
    return {"tunnels": tunnel_manager.list_tunnels()}


# ─── Static Files (Web Dashboard) ───

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the web dashboard."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>DeviceLink Server Running</h1><p>Dashboard not found.</p>")
