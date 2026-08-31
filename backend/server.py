"""
Collaborative Real-Time Text Editor Backend Server.

Unified Asyncio Server (aiohttp):
- Serves static Web UI (HTML, CSS, JS) and full REST CRUD endpoints (/api/documents).
- Handles real-time multi-user document synchronization, rich text formatting (OT), cursors, and presence over WebSockets.
"""

import asyncio
import json
import logging
import mimetypes
import os
import pathlib
import sys
import time
from typing import Dict, Set, Any, Optional

from aiohttp import web, WSMsgType

from .document_manager import DocumentManager, validate_document_id
from .ot import Operation
from .formatting import FormattingStore
from .docx_bridge import docx_to_synapse, synapse_to_docx
from .pdf_exporter import synapse_to_pdf
from .image_store import save_image_file, load_image_file, ALLOWED_EXTENSIONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("CollabServer")


class CollaborativeServer:
    """Server managing HTTP asset delivery, REST CRUD, and real-time WebSocket collaboration."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        frontend_dir: str = "frontend",
        data_dir: str = "data/documents",
    ):
        self.host = host
        self.port = port
        self.frontend_dir = os.path.abspath(frontend_dir)
        self.doc_manager = DocumentManager(storage_dir=data_dir)

        pathlib.Path("data/images").mkdir(parents=True, exist_ok=True)

        # doc_id -> set of active WebSocket connections
        self.doc_clients: Dict[str, Set[web.WebSocketResponse]] = {}
        # websocket connection -> metadata dict {docId, userId, userName, color}
        self.client_meta: Dict[web.WebSocketResponse, Dict[str, Any]] = {}

        self.app = web.Application(client_max_size=50 * 1024 * 1024)  # 50 MB
        self._setup_routes()

    def _setup_routes(self) -> None:
        # REST API endpoints
        self.app.router.add_get("/api/documents", self.handle_list_documents)
        self.app.router.add_post("/api/documents", self.handle_create_document)
        self.app.router.add_get("/api/documents/{doc_id}", self.handle_get_document)
        self.app.router.add_put("/api/documents/{doc_id}", self.handle_rename_document)
        self.app.router.add_delete("/api/documents/{doc_id}", self.handle_delete_document)
        self.app.router.add_get("/api/documents/{doc_id}/export", self.handle_export_document)
        self.app.router.add_post("/api/documents/import", self.handle_import_document)
        self.app.router.add_post("/api/images", self.handle_upload_image)
        self.app.router.add_get("/api/images/{img_id}", self.handle_get_image)

        # WebSocket endpoint
        self.app.router.add_get("/ws", self.ws_handler)
        self.app.router.add_get("/ws/{doc_id}", self.ws_handler)

        # Static files & SPA routing
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/index.html", self.handle_index)
        self.app.router.add_static("/js", os.path.join(self.frontend_dir, "js"), show_index=False)
        self.app.router.add_get("/style.css", self.handle_style_css)
        self.app.router.add_get("/doc/{doc_id}", self.handle_index)

    # -------------------------------------------------------------------------
    # REST API Handlers
    # -------------------------------------------------------------------------

    async def handle_list_documents(self, request: web.Request) -> web.Response:
        """GET /api/documents - Returns list of all active/saved documents."""
        docs = self.doc_manager.list_documents()
        return web.json_response({"documents": docs}, headers={"Access-Control-Allow-Origin": "*"})

    async def handle_create_document(self, request: web.Request) -> web.Response:
        """POST /api/documents - Creates a new document with optional title/docId."""
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        title = data.get("title", "").strip() or None
        doc_id = data.get("docId", "").strip() or None

        try:
            doc = self.doc_manager.create_document(doc_id=doc_id, title=title)
            return web.json_response(
                {"document": doc.to_dict()},
                status=201,
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except ValueError as err:
            return web.json_response(
                {"error": str(err)},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"},
            )

    async def handle_get_document(self, request: web.Request) -> web.Response:
        """GET /api/documents/{doc_id} - Returns metadata and content for a document."""
        doc_id = request.match_info.get("doc_id", "").strip()
        if not doc_id:
            return web.json_response({"error": "Document ID required"}, status=400)

        try:
            doc = self.doc_manager.get_or_create(doc_id)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)
        return web.json_response(
            {"document": doc.to_dict()},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def handle_rename_document(self, request: web.Request) -> web.Response:
        """PUT /api/documents/{doc_id} - Renames a document."""
        doc_id = request.match_info.get("doc_id", "").strip()
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        new_title = data.get("title", "").strip()
        if not new_title:
            return web.json_response({"error": "Title cannot be empty"}, status=400)

        try:
            doc = self.doc_manager.rename_document(doc_id, new_title)
            # Broadcast rename notification to connected clients
            await self.broadcast_to_peers(
                doc_id,
                {"type": "document_renamed", "docId": doc_id, "document": doc.to_dict()},
            )
            return web.json_response(
                {"document": doc.to_dict()},
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except KeyError:
            return web.json_response({"error": f"Document '{doc_id}' not found"}, status=404)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)

    async def handle_delete_document(self, request: web.Request) -> web.Response:
        """DELETE /api/documents/{doc_id} - Deletes a document from memory and disk."""
        doc_id = request.match_info.get("doc_id", "").strip()
        try:
            self.doc_manager.delete_document(doc_id)
            # Notify any connected peers that document was deleted
            await self.broadcast_to_peers(
                doc_id,
                {"type": "document_deleted", "docId": doc_id},
            )
            return web.json_response(
                {"deleted": True, "docId": doc_id},
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)
        except KeyError:
            return web.json_response({"error": f"Document '{doc_id}' not found"}, status=404)

    async def handle_export_document(self, request: web.Request) -> web.Response:
        """GET /api/documents/{doc_id}/export?format=markdown|text|docx - Export file download."""
        doc_id = request.match_info.get("doc_id", "").strip()
        export_format = request.query.get("format", "text").lower()

        try:
            doc = self.doc_manager.get_or_create(doc_id)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)
        if export_format in ("markdown", "md"):
            content = doc.get_markdown()
            content_type = "text/markdown"
            ext = "md"
            body = content.encode("utf-8")
        elif export_format == "json":
            content = json.dumps(doc.to_dict(), indent=2)
            content_type = "application/json"
            ext = "json"
            body = content.encode("utf-8")
        elif export_format == "docx":
            try:
                body = synapse_to_docx(doc.get_content(), doc.formatting.to_list())
            except ValueError as exc:
                return web.json_response(
                    {"error": str(exc)},
                    status=500,
                    headers={"Access-Control-Allow-Origin": "*"},
                )
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ext = "docx"
        elif export_format == "pdf":
            try:
                body = synapse_to_pdf(
                    text=doc.get_content(),
                    formatting_intervals=doc.formatting.to_list(),
                    title=doc.title,
                )
            except Exception as exc:
                return web.json_response(
                    {"error": str(exc)},
                    status=500,
                    headers={"Access-Control-Allow-Origin": "*"},
                )
            content_type = "application/pdf"
            ext = "pdf"
        else:
            content = doc.get_content()
            content_type = "text/plain"
            ext = "txt"
            body = content.encode("utf-8")

        safe_title = "".join(c for c in (doc.title or doc.doc_id) if c.isalnum() or c in (" ", "-", "_")).strip() or doc.doc_id
        filename = f"{safe_title}.{ext}"

        return web.Response(
            body=body,
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Allow-Origin": "*",
            },
        )

    async def handle_import_document(self, request: web.Request) -> web.Response:
        """POST /api/documents/import — import a .docx file into a new document."""
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            return web.json_response(
                {"error": "Missing 'file' field in multipart form data"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        filename = getattr(field, "filename", "") or ""
        if not filename.lower().endswith(".docx"):
            return web.json_response(
                {
                    "error": "Only .docx files are supported. Please convert .doc to .docx first."
                },
                status=400,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        try:
            file_bytes = await field.read()
        except Exception as exc:
            return web.json_response(
                {"error": f"Failed to read uploaded file: {exc}"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        try:
            text, formatting_intervals = docx_to_synapse(file_bytes)
        except ValueError as exc:
            return web.json_response(
                {"error": str(exc)},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        title = filename.rsplit(".", 1)[0] if filename else "Imported Document"
        title = title.strip() or "Imported Document"

        try:
            doc = self.doc_manager.create_document(
                title=title,
                initial_content=text,
                initial_formatting=formatting_intervals,
            )
        except Exception as exc:
            return web.json_response(
                {"error": f"Failed to create document: {exc}"},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        return web.json_response(
            {"document": doc.to_dict()},
            status=201,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def handle_upload_image(self, request: web.Request) -> web.Response:
        """POST /api/images — upload an image and return its imgId."""
        try:
            reader = await request.multipart()
            field = await reader.next()

            if field is None or field.name != "file":
                return web.json_response(
                    {"error": "Missing 'file' field in multipart form data"},
                    status=400,
                    headers={"Access-Control-Allow-Origin": "*"},
                )

            filename = field.filename or ""
            file_bytes = await field.read()

            content_type = field.headers.get("Content-Type", "")
            if not content_type:
                ext = filename.rsplit(".", 1)[-1].lower()
                content_type = {
                    "png":  "image/png",
                    "jpg":  "image/jpeg",
                    "jpeg": "image/jpeg",
                    "gif":  "image/gif",
                    "webp": "image/webp",
                    "bmp":  "image/bmp",
                    "tif":  "image/tiff",
                    "tiff": "image/tiff",
                }.get(ext, "application/octet-stream")

            if content_type not in ALLOWED_EXTENSIONS:
                return web.json_response(
                    {"error": "Unsupported image type. Use PNG, JPG, GIF, WebP, BMP, or TIFF."},
                    status=400,
                    headers={"Access-Control-Allow-Origin": "*"},
                )

            img_id = save_image_file(file_bytes, content_type)
            return web.json_response(
                {"imgId": img_id, "url": f"/api/images/{img_id}"},
                status=201,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response(
                {"error": str(e)},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"},
            )

    async def handle_get_image(self, request: web.Request) -> web.Response:
        """GET /api/images/{img_id} — serve a stored image."""
        img_id = request.match_info.get("img_id", "").strip()
        if not img_id:
            return web.Response(status=404, headers={"Access-Control-Allow-Origin": "*"})

        try:
            image_bytes, content_type = load_image_file(img_id)
        except FileNotFoundError:
            return web.Response(status=404, headers={"Access-Control-Allow-Origin": "*"})

        return web.Response(
            body=image_bytes,
            content_type=content_type,
            headers={
                "Cache-Control": "public, max-age=31536000",
                "Access-Control-Allow-Origin": "*",
            },
        )

    # -------------------------------------------------------------------------
    # Static File Handlers
    # -------------------------------------------------------------------------

    async def handle_index(self, request: web.Request) -> web.FileResponse:
        index_file = os.path.join(self.frontend_dir, "index.html")
        return web.FileResponse(index_file, headers={"Cache-Control": "no-cache"})

    async def handle_style_css(self, request: web.Request) -> web.FileResponse:
        css_file = os.path.join(self.frontend_dir, "style.css")
        return web.FileResponse(css_file, headers={"Cache-Control": "no-cache"})

    # -------------------------------------------------------------------------
    # WebSocket Real-Time Collaboration
    # -------------------------------------------------------------------------

    async def broadcast_to_peers(
        self, doc_id: str, message: Dict[str, Any], exclude_socket: Optional[web.WebSocketResponse] = None
    ) -> None:
        """Sends a JSON message to all clients subscribed to doc_id except exclude_socket."""
        if doc_id not in self.doc_clients:
            return

        payload = json.dumps(message)
        dead_sockets: Set[web.WebSocketResponse] = set()

        for ws in list(self.doc_clients[doc_id]):
            if ws is not exclude_socket and not ws.closed:
                try:
                    await ws.send_str(payload)
                except Exception:
                    dead_sockets.add(ws)

        for dead_ws in dead_sockets:
            await self._cleanup_client(dead_ws)

    async def _cleanup_client(self, websocket: web.WebSocketResponse) -> None:
        """Handles socket disconnect cleanup and notifies peer clients."""
        meta = self.client_meta.pop(websocket, None)
        if not meta:
            return

        doc_id = meta.get("docId")
        user_id = meta.get("userId")
        user_name = meta.get("userName")

        if doc_id and doc_id in self.doc_clients:
            self.doc_clients[doc_id].discard(websocket)
            if not self.doc_clients[doc_id]:
                del self.doc_clients[doc_id]

            doc = self.doc_manager.get_or_create(doc_id)
            doc.remove_user(user_id)
            self.doc_manager.save_document(doc_id)

            logger.info(f"User {user_name} ({user_id}) left document {doc_id}")

            # Notify peers
            await self.broadcast_to_peers(
                doc_id,
                {
                    "type": "user_left",
                    "docId": doc_id,
                    "userId": user_id,
                    "activeUsers": doc.get_users_list(),
                },
            )

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handles incoming WebSocket connection lifecycle and messages."""
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)

        logger.info(f"New client connected from {request.remote}")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON received: {msg.data}")
                        continue

                    msg_type = data.get("type")

                    # 1. Join Document
                    if msg_type == "join":
                        if ws in self.client_meta:
                            await ws.send_str(json.dumps({"type": "error", "message": "A connection may join only one document"}))
                            continue

                        try:
                            doc_id = validate_document_id(data.get("docId", "welcome") or "welcome")
                        except ValueError as err:
                            await ws.send_str(json.dumps({"type": "error", "message": str(err)}))
                            continue
                        user_id = (data.get("userId") or "").strip()
                        if not user_id:
                            await ws.send_str(json.dumps({"type": "error", "message": "User ID is required"}))
                            continue
                        user_name = data.get("userName", "Anonymous")
                        color = data.get("color", "#4285F4")

                        # Register client
                        self.client_meta[ws] = {
                            "docId": doc_id,
                            "userId": user_id,
                            "userName": user_name,
                            "color": color,
                        }
                        if doc_id not in self.doc_clients:
                            self.doc_clients[doc_id] = set()
                        self.doc_clients[doc_id].add(ws)

                        doc = self.doc_manager.get_or_create(doc_id)
                        user_state = doc.add_user(user_id, user_name, color)

                        logger.info(f"User '{user_name}' ({user_id}) joined doc '{doc_id}' (v{doc.version})")

                        # Send initial sync payload to joining client
                        init_packet = {
                            "type": "init",
                            "docId": doc_id,
                            "title": doc.title,
                            "content": doc.get_content(),
                            "formatting": doc.formatting.to_list(),
                            "version": doc.version,
                            "users": doc.get_users_list(),
                            "history": doc.get_history_summary(),
                        }
                        await ws.send_str(json.dumps(init_packet))

                        # Broadcast new user presence to other peers
                        await self.broadcast_to_peers(
                            doc_id,
                            {
                                "type": "user_joined",
                                "docId": doc_id,
                                "user": user_state.to_dict(),
                                "activeUsers": doc.get_users_list(),
                            },
                            exclude_socket=ws,
                        )

                    # 2. Text / Format Operation (OT)
                    elif msg_type == "operation":
                        doc_id = data.get("docId")
                        client_version = data.get("version", 0)
                        op_data = data.get("op", {})
                        meta = self.client_meta.get(ws)

                        if not meta or doc_id != meta["docId"]:
                            await ws.send_str(json.dumps({"type": "error", "message": "Operation is not authorized for this document"}))
                            continue

                        doc = self.doc_manager.get_or_create(doc_id)
                        op = Operation.from_dict(op_data)
                        user_id = meta["userId"]
                        op.user_id = user_id

                        try:
                            transformed_op, new_version = doc.apply_client_operation(
                                op, client_base_version=client_version
                            )
                        except Exception as err:
                            logger.error(f"Error applying operation to {doc_id}: {err}")
                            continue

                        # Send Ack to author
                        ack_packet = {
                            "type": "ack",
                            "docId": doc_id,
                            "opId": op.op_id,
                            "version": new_version,
                        }
                        await ws.send_str(json.dumps(ack_packet))

                        # Broadcast transformed operation to peer clients
                        if not transformed_op.is_noop():
                            broadcast_packet = {
                                "type": "operation",
                                "docId": doc_id,
                                "userId": user_id,
                                "version": new_version,
                                "op": transformed_op.to_dict(),
                            }
                            await self.broadcast_to_peers(doc_id, broadcast_packet, exclude_socket=ws)

                    # 3. Cursor & Selection Presence
                    elif msg_type == "cursor":
                        doc_id = data.get("docId")
                        cursor_pos = data.get("cursor", {})
                        meta = self.client_meta.get(ws)

                        if meta and doc_id == meta["docId"]:
                            user_id = meta["userId"]
                            doc = self.doc_manager.get_or_create(doc_id)
                            doc.update_cursor(user_id, cursor_pos)

                            await self.broadcast_to_peers(
                                doc_id,
                                {
                                    "type": "cursor",
                                    "docId": doc_id,
                                    "userId": user_id,
                                    "cursor": cursor_pos,
                                },
                                exclude_socket=ws,
                            )

                    # 4. Version History Request
                    elif msg_type == "get_history":
                        doc_id = data.get("docId")
                        meta = self.client_meta.get(ws)
                        if meta and doc_id == meta["docId"]:
                            doc = self.doc_manager.get_or_create(doc_id)
                            history_packet = {
                                "type": "history_list",
                                "docId": doc_id,
                                "currentVersion": doc.version,
                                "snapshots": sorted(list(doc.snapshots.keys())),
                                "history": doc.get_history_summary(),
                            }
                            await ws.send_str(json.dumps(history_packet))

                    # 5. Snapshot Preview Request
                    elif msg_type == "get_snapshot":
                        doc_id = data.get("docId")
                        target_version = data.get("version", 0)
                        meta = self.client_meta.get(ws)
                        if meta and doc_id == meta["docId"]:
                            doc = self.doc_manager.get_or_create(doc_id)
                            try:
                                content = doc.get_snapshot_at_version(target_version)
                                formatting = doc.get_snapshot_formatting_at_version(target_version)
                            except ValueError as err:
                                await ws.send_str(json.dumps({"type": "error", "message": str(err)}))
                                continue
                            await ws.send_str(
                                json.dumps(
                                    {
                                        "type": "snapshot_content",
                                        "docId": doc_id,
                                        "version": target_version,
                                        "content": content,
                                        "formatting": formatting,
                                    }
                                )
                            )

                    # 6. Restore Document to Past Version
                    elif msg_type == "restore_version":
                        doc_id = data.get("docId")
                        target_version = data.get("version", 0)
                        meta = self.client_meta.get(ws)
                        if meta and doc_id == meta["docId"]:
                            user_id = meta["userId"]
                            doc = self.doc_manager.get_or_create(doc_id)
                            try:
                                past_content = doc.get_snapshot_at_version(target_version)
                            except ValueError as err:
                                await ws.send_str(json.dumps({"type": "error", "message": str(err)}))
                                continue
                            if past_content is not None:
                                current_len = doc.length()
                                if current_len > 0:
                                    del_op = Operation.from_dict({
                                        "type": "delete",
                                        "pos": 0,
                                        "length": current_len,
                                        "userId": user_id,
                                    })
                                    doc.apply_client_operation(del_op, client_base_version=doc.version)

                                if len(past_content) > 0:
                                    ins_op = Operation.from_dict({
                                        "type": "insert",
                                        "pos": 0,
                                        "text": past_content,
                                        "userId": user_id,
                                    })
                                    doc.apply_client_operation(ins_op, client_base_version=doc.version)

                                # Reset formatting to the target version
                                doc.formatting = FormattingStore(
                                    doc.get_snapshot_formatting_at_version(target_version)
                                )

                                sync_packet = {
                                    "type": "reset_sync",
                                    "docId": doc_id,
                                    "content": doc.get_content(),
                                    "formatting": doc.formatting.to_list(),
                                    "version": doc.version,
                                    "message": f"Document restored to version {target_version}",
                                }
                                await self.broadcast_to_peers(doc_id, sync_packet, exclude_socket=ws)
                                await ws.send_str(json.dumps(sync_packet))

                    # 7. Document CRUD over WebSocket
                    elif msg_type == "create_document":
                        new_title = (data.get("title") or "").strip() or None
                        new_id = (data.get("docId") or "").strip() or None
                        try:
                            doc = self.doc_manager.create_document(new_id, new_title)
                            await ws.send_str(json.dumps({
                                "type": "document_created",
                                "document": doc.to_dict(),
                            }))
                        except Exception as err:
                            await ws.send_str(json.dumps({
                                "type": "error",
                                "message": str(err),
                            }))

                    elif msg_type == "rename_document":
                        doc_id = data.get("docId", "")
                        new_title = (data.get("title") or "").strip()
                        meta = self.client_meta.get(ws)
                        if meta and doc_id == meta["docId"] and new_title:
                            try:
                                doc = self.doc_manager.rename_document(doc_id, new_title)
                                await ws.send_str(json.dumps({
                                    "type": "document_renamed",
                                    "document": doc.to_dict(),
                                }))
                                await self.broadcast_to_peers(
                                    doc_id,
                                    {"type": "document_renamed", "document": doc.to_dict()},
                                    exclude_socket=ws,
                                )
                            except Exception as err:
                                await ws.send_str(json.dumps({"type": "error", "message": str(err)}))

                    elif msg_type == "delete_document":
                        doc_id = data.get("docId", "")
                        meta = self.client_meta.get(ws)
                        if meta and doc_id == meta["docId"]:
                            try:
                                self.doc_manager.delete_document(doc_id)
                                await ws.send_str(json.dumps({
                                    "type": "document_deleted",
                                    "docId": doc_id,
                                }))
                                await self.broadcast_to_peers(
                                    doc_id,
                                    {"type": "document_deleted", "docId": doc_id},
                                    exclude_socket=ws,
                                )
                            except Exception as err:
                                await ws.send_str(json.dumps({"type": "error", "message": str(err)}))

                    # 8. Ping / Pong Latency Check
                    elif msg_type == "ping":
                        await ws.send_str(
                            json.dumps({"type": "pong", "timestamp": data.get("timestamp")})
                        )

                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket connection closed with exception: {ws.exception()}")

        except Exception as e:
            logger.error(f"WebSocket client exception: {e}")
        finally:
            await self._cleanup_client(ws)

        return ws

    async def start(self) -> None:
        """Starts the aiohttp HTTP + WebSocket server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        logger.info(f"Synapse Server running at http://{self.host}:{self.port}")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("Shutting down server...")
            await runner.cleanup()
            self.doc_manager.save_all()
            logger.info("All documents saved. Goodbye.")


def main():
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    server = CollaborativeServer(host=host, port=port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")


if __name__ == "__main__":
    main()
