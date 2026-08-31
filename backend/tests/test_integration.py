"""
Integration tests simulating multiple concurrent WebSocket clients interacting with CollaborativeServer.
"""

import asyncio
import json
import shutil
import tempfile
import unittest
import aiohttp
from aiohttp import web
from backend.server import CollaborativeServer


class TestServerIntegration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.port = 8795
        self.host = "127.0.0.1"
        self.server_obj = CollaborativeServer(host=self.host, port=self.port, data_dir=self.test_dir)
        
        self.runner = web.AppRunner(self.server_obj.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        self.ws_url = f"http://{self.host}:{self.port}/ws"

    async def asyncTearDown(self):
        await self.runner.cleanup()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_single_client_join_and_edit(self):
        """Test single client joining, editing, and receiving an ack."""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.ws_url) as ws:
                # Send join
                join_msg = {
                    "type": "join",
                    "docId": "doc_single",
                    "userId": "user1",
                    "userName": "Alice",
                    "color": "#4285F4",
                }
                await ws.send_str(json.dumps(join_msg))

                # Receive init
                msg = await ws.receive()
                init_resp = json.loads(msg.data)
                self.assertEqual(init_resp["type"], "init")
                self.assertEqual(init_resp["docId"], "doc_single")
                self.assertEqual(init_resp["version"], 0)

                # Send operation
                op_msg = {
                    "type": "operation",
                    "docId": "doc_single",
                    "userId": "user1",
                    "version": 0,
                    "op": {
                        "type": "insert",
                        "pos": 0,
                        "text": "Hello Collaborative World!",
                        "opId": "op1",
                    },
                }
                await ws.send_str(json.dumps(op_msg))

                # Receive ack
                msg_ack = await ws.receive()
                ack_resp = json.loads(msg_ack.data)
                self.assertEqual(ack_resp["type"], "ack")
                self.assertEqual(ack_resp["opId"], "op1")
                self.assertEqual(ack_resp["version"], 1)

                # Check document state
                doc = self.server_obj.doc_manager.get_or_create("doc_single")
                self.assertEqual(doc.get_content(), "Hello Collaborative World!")
                self.assertEqual(doc.version, 1)

    async def test_multi_client_concurrent_edits_convergence(self):
        """Simulates two clients joining the same document and sending concurrent operations."""
        async with aiohttp.ClientSession() as session1, aiohttp.ClientSession() as session2:
            async with session1.ws_connect(self.ws_url) as ws1, session2.ws_connect(self.ws_url) as ws2:
                # Client 1 joins
                await ws1.send_str(json.dumps({
                    "type": "join",
                    "docId": "doc_collab",
                    "userId": "alice",
                    "userName": "Alice",
                    "color": "#FF5722",
                }))
                msg1 = await ws1.receive()
                init1 = json.loads(msg1.data)
                self.assertEqual(init1["type"], "init")

                # Client 2 joins
                await ws2.send_str(json.dumps({
                    "type": "join",
                    "docId": "doc_collab",
                    "userId": "bob",
                    "userName": "Bob",
                    "color": "#4CAF50",
                }))
                msg2 = await ws2.receive()
                init2 = json.loads(msg2.data)
                self.assertEqual(init2["type"], "init")

                # Client 1 receives user_joined notification for Bob
                msg_for_c1 = json.loads((await ws1.receive()).data)
                self.assertEqual(msg_for_c1["type"], "user_joined")

                # Alice sends insert at index 0 (base version 0)
                await ws1.send_str(json.dumps({
                    "type": "operation",
                    "docId": "doc_collab",
                    "userId": "alice",
                    "version": 0,
                    "op": {
                        "type": "insert",
                        "pos": 0,
                        "text": "Alice writes first. ",
                        "opId": "op_a1",
                    },
                }))

                # Bob simultaneously sends insert at index 0 (base version 0)
                await ws2.send_str(json.dumps({
                    "type": "operation",
                    "docId": "doc_collab",
                    "userId": "bob",
                    "version": 0,
                    "op": {
                        "type": "insert",
                        "pos": 0,
                        "text": "Bob writes too. ",
                        "opId": "op_b1",
                    },
                }))

                # Read acks and broadcast messages
                resp1_1 = json.loads((await ws1.receive()).data)
                resp1_2 = json.loads((await ws1.receive()).data)

                resp2_1 = json.loads((await ws2.receive()).data)
                resp2_2 = json.loads((await ws2.receive()).data)

                doc = self.server_obj.doc_manager.get_or_create("doc_collab")
                self.assertEqual(doc.version, 2)
                final_content = doc.get_content()
                
                self.assertIn("Alice writes first.", final_content)
                self.assertIn("Bob writes too.", final_content)

    async def test_cursor_and_presence_broadcast(self):
        """Tests cursor movements being broadcasted to other clients."""
        async with aiohttp.ClientSession() as session1, aiohttp.ClientSession() as session2:
            async with session1.ws_connect(self.ws_url) as ws1, session2.ws_connect(self.ws_url) as ws2:
                # Client 1 joins
                await ws1.send_str(json.dumps({"type": "join", "docId": "doc_cursor", "userId": "u1", "userName": "U1"}))
                await ws1.receive()  # init

                # Client 2 joins
                await ws2.send_str(json.dumps({"type": "join", "docId": "doc_cursor", "userId": "u2", "userName": "U2"}))
                await ws2.receive()  # init
                await ws1.receive()  # user_joined

                # Client 1 moves cursor
                cursor_payload = {
                    "type": "cursor",
                    "docId": "doc_cursor",
                    "userId": "u1",
                    "cursor": {"start": 10, "end": 15, "line": 2, "col": 5},
                }
                await ws1.send_str(json.dumps(cursor_payload))

                # Client 2 receives cursor update
                received_cursor = json.loads((await ws2.receive()).data)
                self.assertEqual(received_cursor["type"], "cursor")
                self.assertEqual(received_cursor["userId"], "u1")
                self.assertEqual(received_cursor["cursor"]["start"], 10)
                self.assertEqual(received_cursor["cursor"]["end"], 15)

    async def test_websocket_cannot_edit_another_document(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.ws_url) as ws:
                await ws.send_str(json.dumps({
                    "type": "join", "docId": "allowed-doc", "userId": "u1", "userName": "U1"
                }))
                await ws.receive()  # init

                await ws.send_str(json.dumps({
                    "type": "operation",
                    "docId": "other-doc",
                    "userId": "spoofed-user",
                    "version": 0,
                    "op": {"type": "insert", "pos": 0, "text": "unauthorized"},
                }))
                response = json.loads((await ws.receive()).data)
                self.assertEqual(response["type"], "error")
                self.assertNotIn("other-doc", self.server_obj.doc_manager.documents)


if __name__ == "__main__":
    unittest.main()
