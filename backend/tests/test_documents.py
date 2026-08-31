"""
Tests for Document CRUD, disk persistence, export, and server-side document
management over REST API and WebSocket.
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
import aiohttp
from aiohttp import web

from backend.document_manager import DocumentManager, Document
from backend.ot import InsertOp, FormatOp
from backend.server import CollaborativeServer


class TestDocumentCRUD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mgr = DocumentManager(storage_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_list(self):
        doc = self.mgr.create_document(title="My Notes")
        self.assertIn(doc.doc_id, self.mgr.documents)
        ids = [d["docId"] for d in self.mgr.list_documents()]
        self.assertIn(doc.doc_id, ids)

    def test_rename(self):
        doc = self.mgr.create_document(title="Old")
        self.mgr.rename_document(doc.doc_id, "New Title")
        self.assertEqual(self.mgr.documents[doc.doc_id].title, "New Title")

    def test_delete(self):
        doc = self.mgr.create_document(title="ToDelete")
        path = os.path.join(self.tmp, f"{doc.doc_id}.json")
        self.assertTrue(os.path.exists(path))
        self.mgr.delete_document(doc.doc_id)
        self.assertNotIn(doc.doc_id, self.mgr.documents)
        self.assertFalse(os.path.exists(path))

    def test_rejects_path_traversal_document_id(self):
        with self.assertRaises(ValueError):
            self.mgr.create_document(doc_id="../../outside")

    def test_delete_missing_document_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.mgr.delete_document("does-not-exist")

    def test_rejects_invalid_snapshot_version(self):
        doc = self.mgr.create_document(doc_id="snapshot-check")
        with self.assertRaises(ValueError):
            doc.get_snapshot_at_version(1)
        with self.assertRaises(ValueError):
            doc.get_snapshot_formatting_at_version(-1)

    def test_persistence_round_trip(self):
        doc = self.mgr.create_document(title="Persist Me")
        doc.apply_client_operation(InsertOp(0, "Hello world", user_id="u"), client_base_version=0)
        doc.apply_client_operation(
            FormatOp(0, 5, {"bold": True}, user_id="u"), client_base_version=1
        )
        self.mgr.save_all()

        # Reload from disk with a fresh manager.
        mgr2 = DocumentManager(storage_dir=self.tmp)
        loaded = mgr2.get_or_create(doc.doc_id)
        self.assertEqual(loaded.get_content(), "Hello world")
        self.assertEqual(loaded.formatting.to_list(), [[0, 5, {"bold": True}]])
        self.assertEqual(loaded.get_markdown(), "**Hello** world")

    def test_markdown_export(self):
        doc = Document("exp", initial_text="Hello world")
        doc.apply_client_operation(FormatOp(0, 5, {"bold": True}), client_base_version=0)
        doc.apply_client_operation(FormatOp(0, 11, {"header": 1}), client_base_version=1)
        self.assertEqual(doc.get_markdown(), "# **Hello** world")

    def test_concurrent_formatting_convergence(self):
        # Two clients format overlapping ranges from the same base version.
        doc = Document("conv", initial_text="collaborative editing")
        a = FormatOp(0, 11, {"bold": True}, user_id="a", op_id="a1")
        b = FormatOp(5, 13, {"italic": True}, user_id="b", op_id="a2")

        t_a, v_a = doc.apply_client_operation(a, client_base_version=0)
        t_b, v_b = doc.apply_client_operation(b, client_base_version=0)

        # Server state is deterministic. A client replaying both transformed ops
        # in arrival order must reproduce it.
        replay = Document("conv", initial_text="collaborative editing")
        replay.apply_client_operation(t_a, client_base_version=0)
        replay.apply_client_operation(t_b, client_base_version=1)
        self.assertEqual(replay.formatting.to_list(), doc.formatting.to_list())
        self.assertEqual(replay.get_content(), doc.get_content())


class TestServerRESTAndWebSocket(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.port = 8792
        self.host = "127.0.0.1"
        self.server_obj = CollaborativeServer(host=self.host, port=self.port, data_dir=self.tmp)
        
        self.runner = web.AppRunner(self.server_obj.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        self.http_url = f"http://{self.host}:{self.port}"
        self.ws_url = f"ws://{self.host}:{self.port}/ws"

    async def asyncTearDown(self):
        await self.runner.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_rest_crud_endpoints(self):
        async with aiohttp.ClientSession() as session:
            # 1. POST /api/documents (Create)
            async with session.post(f"{self.http_url}/api/documents", json={"title": "REST Created Doc"}) as resp:
                self.assertEqual(resp.status, 201)
                data = await resp.json()
                doc_id = data["document"]["docId"]
                self.assertEqual(data["document"]["title"], "REST Created Doc")

            # 2. GET /api/documents (List)
            async with session.get(f"{self.http_url}/api/documents") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                ids = [d["docId"] for d in data["documents"]]
                self.assertIn(doc_id, ids)

            # 3. GET /api/documents/:id (Get details)
            async with session.get(f"{self.http_url}/api/documents/{doc_id}") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data["document"]["docId"], doc_id)

            # 4. PUT /api/documents/:id (Rename)
            async with session.put(f"{self.http_url}/api/documents/{doc_id}", json={"title": "Renamed Title"}) as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data["document"]["title"], "Renamed Title")

            # 5. DELETE /api/documents/:id (Delete)
            async with session.delete(f"{self.http_url}/api/documents/{doc_id}") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data["deleted"])

            # 6. Verify deleted from list
            async with session.get(f"{self.http_url}/api/documents") as resp:
                data = await resp.json()
                ids = [d["docId"] for d in data["documents"]]
                self.assertNotIn(doc_id, ids)

    async def test_rest_export_endpoint(self):
        # Create and format document
        doc = self.server_obj.doc_manager.create_document(doc_id="export-test", title="Export Test")
        doc.apply_client_operation(InsertOp(0, "Rich Text Content", user_id="u"), client_base_version=0)
        doc.apply_client_operation(FormatOp(0, 9, {"bold": True}, user_id="u"), client_base_version=1)

        async with aiohttp.ClientSession() as session:
            # Markdown export
            async with session.get(f"{self.http_url}/api/documents/export-test/export?format=markdown") as resp:
                self.assertEqual(resp.status, 200)
                text = await resp.text()
                self.assertEqual(text, "**Rich Text** Content")

            # Plain text export
            async with session.get(f"{self.http_url}/api/documents/export-test/export?format=text") as resp:
                self.assertEqual(resp.status, 200)
                text = await resp.text()
                self.assertEqual(text, "Rich Text Content")


if __name__ == "__main__":
    unittest.main()
