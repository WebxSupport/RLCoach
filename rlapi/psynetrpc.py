"""PsyNetRPC WebSocket client for Rocket League API."""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
from enum import Enum, auto
from dataclasses import dataclass
from typing import Any, Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from .psynet import PSY_BUILD_ID, GAME_VERSION, PING_INTERVAL, PONG_TIMEOUT, PsyNetError, PSY_SIG_KEY
from .requestid import RequestIDCounter
from .playerid import PlayerID


class EventType(Enum):
    DISCONNECTED = auto()
    MESSAGE = auto()


@dataclass
class Event:
    type: EventType
    content: str


@dataclass
class PsyResponse:
    response_id: str
    result: Any
    error: Optional[Dict[str, str]] = None


class PsyNetRPC:
    """Authenticated WebSocket connection to PsyNet."""

    def __init__(
        self,
        ws_conn: WebSocketClientProtocol,
        local_player_id: PlayerID,
        psy_token: str,
        session_id: str,
        request_id: RequestIDCounter,
        logger: Optional[logging.Logger] = None,
    ):
        self.ws_conn = ws_conn
        self.local_player_id = local_player_id
        self.psy_token = psy_token
        self.session_id = session_id
        self.request_id = request_id
        self.logger = logger or logging.getLogger(__name__)

        self._lock = asyncio.Lock()
        self._pending_reqs: Dict[str, asyncio.Queue] = {}
        self._pong_event = asyncio.Event()
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._connected = True
        self._ping_task: Optional[asyncio.Task] = None
        self._read_task: Optional[asyncio.Task] = None

    def is_connected(self) -> bool:
        return self._connected and self.ws_conn is not None

    async def close(self) -> None:
        async with self._lock:
            if self.ws_conn and self._connected:
                try:
                    await self.ws_conn.close(code=1000, reason="Normal closure")
                except Exception:
                    pass
                self._connected = False
                if self._ping_task:
                    self._ping_task.cancel()
                    self._ping_task = None
                if self._read_task:
                    self._read_task.cancel()
                    self._read_task = None
                self._pending_reqs.clear()
        try:
            await self._event_queue.put(Event(type=EventType.DISCONNECTED, content=""))
        except asyncio.QueueFull:
            pass

    def _parse_message(self, message: str) -> PsyResponse:
        delimiter = "\r\n\r\n"
        index = message.find(delimiter)
        if index == -1:
            raise ValueError("Message missing delimiter")
        headers_part = message[:index]
        json_payload = message[index + len(delimiter):]
        headers = {}
        for line in headers_part.split("\r\n"):
            colon_index = line.find(":")
            if colon_index != -1:
                headers[line[:colon_index].strip()] = line[colon_index + 1:].strip()
        response_id = headers.get("PsyResponseID", "")
        json_result = json.loads(json_payload)
        error = json_result.get("Error") or None
        return PsyResponse(response_id=response_id, result=json_result.get("Result"), error=error)

    def _build_message(self, headers: Dict[str, str], body: Optional[Any] = None) -> str:
        json_data = b""
        if body is not None:
            json_data = json.dumps(body).encode()
            h = hmac.new(PSY_SIG_KEY.encode(), digestmod=hashlib.sha256)
            h.update(b"-")
            h.update(json_data)
            headers["PsySig"] = base64.b64encode(h.digest()).decode()
        message = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
        return message + "\r\n\r\n" + json_data.decode()

    async def _schedule_ping(self) -> None:
        await asyncio.sleep(PING_INTERVAL)
        await self._send_ping()

    async def _send_ping(self) -> None:
        ping_message = self._build_message({"PsyPing": ""}, None)
        async with self._lock:
            if not self._connected or not self.ws_conn:
                return
            try:
                await self.ws_conn.send(ping_message)
            except Exception as e:
                self.logger.error("Failed to send ping: %s", e)
                return
        self._pong_event.clear()
        try:
            await asyncio.wait_for(self._pong_event.wait(), timeout=PONG_TIMEOUT)
            self._ping_task = asyncio.create_task(self._schedule_ping())
        except asyncio.TimeoutError:
            self.logger.error("Pong timeout — closing connection")
            await self.close()

    async def _read_messages(self) -> None:
        try:
            async for message in self.ws_conn:
                if isinstance(message, bytes):
                    message = message.decode()
                if message.startswith("PsyPong:"):
                    self._pong_event.set()
                    continue
                self.logger.debug("WS ← %s", message[:120])
                try:
                    response = self._parse_message(message)
                    if response.response_id:
                        async with self._lock:
                            if response.response_id in self._pending_reqs:
                                await self._pending_reqs[response.response_id].put(response)
                                continue
                    try:
                        await self._event_queue.put(Event(type=EventType.MESSAGE, content=message))
                    except asyncio.QueueFull:
                        pass
                except Exception as e:
                    self.logger.error("Failed to parse message: %s", e)
        except Exception as e:
            self.logger.error("WebSocket read error: %s", e)
        finally:
            await self.close()

    async def send_request_async(self, service: str, data: Any) -> asyncio.Queue:
        if not self.is_connected():
            raise Exception("WebSocket not connected")
        request_id = self.request_id.get_id()
        self.logger.debug("WS → %s (%s)", service, request_id)
        resp_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        headers = {"PsyService": service, "PsyRequestID": request_id}
        message = self._build_message(headers, data)
        async with self._lock:
            if not self._connected or not self.ws_conn:
                raise Exception("Connection lost before send")
            self._pending_reqs[request_id] = resp_queue
            try:
                await self.ws_conn.send(message)
            except Exception as e:
                del self._pending_reqs[request_id]
                raise Exception(f"Send failed: {e}")
        return resp_queue

    async def await_response(self, resp_queue: asyncio.Queue, timeout: Optional[float] = None) -> Any:
        response = await asyncio.wait_for(resp_queue.get(), timeout=timeout)
        if response.error:
            raise PsyNetError(
                type=response.error.get("Type", ""),
                message=response.error.get("Message", ""),
            )
        return response.result

    async def send_request_sync(self, service: str, data: Any, timeout: Optional[float] = None) -> Any:
        resp_queue = await self.send_request_async(service, data)
        return await self.await_response(resp_queue, timeout)

    def start_background_tasks(self) -> None:
        self._read_task = asyncio.create_task(self._read_messages())
        self._ping_task = asyncio.create_task(self._schedule_ping())
