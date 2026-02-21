"""Système de log en temps réel pour les jobs, basé sur asyncio.Queue (pub/sub in-memory)."""

import asyncio
import json
from datetime import datetime
from typing import Literal

ServiceName = Literal["vision", "elevenlabs", "kie", "ffmpeg", "pipeline"]
LogLevel = Literal["info", "success", "warning", "error"]

# Subscribers : job_id → liste de queues SSE
_subscribers: dict[str, list[asyncio.Queue]] = {}


def emit(job_id: str, service: ServiceName, level: LogLevel, message: str) -> None:
    """Émet un log vers tous les clients SSE abonnés à ce job."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": service,
        "level": level,
        "message": message,
    }
    queues = _subscribers.get(job_id, [])
    for q in queues:
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            pass  # Drop si le client est trop lent


def subscribe(job_id: str) -> asyncio.Queue:
    """Crée une queue et l'abonne aux logs du job."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: str, q: asyncio.Queue) -> None:
    """Retire une queue de la liste des abonnés."""
    queues = _subscribers.get(job_id, [])
    try:
        queues.remove(q)
    except ValueError:
        pass
    if not queues:
        _subscribers.pop(job_id, None)


def format_sse(entry: dict) -> str:
    """Formate un LogEntry en message SSE."""
    return f"data: {json.dumps(entry)}\n\n"
