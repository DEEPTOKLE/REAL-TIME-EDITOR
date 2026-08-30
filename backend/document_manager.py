"""
Document Manager and Document State Management.

Manages active documents, Rope data structures, version history, snapshots,
active user presence/cursors, and optional disk persistence.
"""

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Any, Tuple
from .rope import Rope
from .ot import Operation, InsertOp, DeleteOp, NoOp, FormatOp, transform
from .formatting import FormattingStore


class UserState:
    """Represents a connected user's state."""

    def __init__(self, user_id: str, user_name: str, color: str):
        self.user_id = user_id
        self.user_name = user_name
        self.color = color
        self.cursor_pos: Dict[str, Any] = {"start": 0, "end": 0, "line": 1, "col": 1}
        self.last_active: float = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "userId": self.user_id,
            "userName": self.user_name,
            "color": self.color,
            "cursor": self.cursor_pos,
            "lastActive": self.last_active,
        }


class Document:
    """
    Authoritative state for a collaborative document.
    Maintains the balanced Rope, operation history log, snapshots, and active users.
    """

    SNAPSHOT_INTERVAL: int = 10

    def __init__(self, doc_id: str, title: str = "Untitled Document", initial_text: str = ""):
        self.doc_id = doc_id
        self.title = title
        self.rope = Rope(initial_text)
        self.version = 0
        self.history: List[Operation] = []
        self.history_metadata: List[Dict[str, Any]] = []
        self.snapshots: Dict[int, str] = {0: initial_text}
        self.snapshots_formatting: Dict[int, list] = {0: []}
        self.formatting: FormattingStore = FormattingStore()
        self.active_users: Dict[str, UserState] = {}
        self.created_at = time.time()
        self.updated_at = time.time()

    def get_content(self) -> str:
        """Returns the full text of the document from the Rope."""
        return self.rope.to_string()

    def get_markdown(self) -> str:
        """Returns the document rendered as Markdown (formatting applied)."""
        return self.formatting.to_markdown(self.get_content())

    def length(self) -> int:
        return self.rope.length()

    def apply_client_operation(
        self, op: Operation, client_base_version: int
    ) -> Tuple[Operation, int]:
        """
        Transforms an incoming client operation against all concurrent operations
        in document history between client_base_version and current document version,
        applies the transformed operation to the authoritative Rope, increments
        the document version, and logs it.
        """
        if client_base_version < 0 or client_base_version > self.version:
            raise ValueError(
                f"Invalid client base version {client_base_version}; document is at {self.version}"
            )

        transformed_op = op

        # Transform against all concurrent operations applied since client's base version
        for past_op in self.history[client_base_version:self.version]:
            transformed_op, _ = transform(transformed_op, past_op)
            if transformed_op.is_noop():
                break

        # Apply to Rope + formatting store
        if isinstance(transformed_op, InsertOp):
            if transformed_op.pos > self.rope.length():
                transformed_op.pos = self.rope.length()
            self.rope.insert(transformed_op.pos, transformed_op.text)
            self.formatting.insert(transformed_op.pos, len(transformed_op.text))
        elif isinstance(transformed_op, DeleteOp):
            if transformed_op.pos < self.rope.length():
                end_pos = min(self.rope.length(), transformed_op.pos + transformed_op.length)
                # Capture deleted text if missing
                if not transformed_op.text and end_pos > transformed_op.pos:
                    transformed_op.text = self.rope.substring(transformed_op.pos, end_pos)
                self.rope.delete(transformed_op.pos, end_pos)
                self.formatting.delete(transformed_op.pos, end_pos)
        elif isinstance(transformed_op, FormatOp):
            if transformed_op.end > transformed_op.start:
                # Capture previous attributes so the op can be inverted (undo).
                prev = self.formatting.attrs_in_range(
                    transformed_op.start, transformed_op.end
                )
                transformed_op.prev_attributes = prev
                self.formatting.format(
                    transformed_op.start, transformed_op.end, transformed_op.attributes
                )

        # Append to operation history
        self.history.append(transformed_op)
        self.history_metadata.append({
            "version": self.version + 1,
            "userId": transformed_op.user_id,
            "type": "insert" if isinstance(transformed_op, InsertOp) else ("delete" if isinstance(transformed_op, DeleteOp) else ("format" if isinstance(transformed_op, FormatOp) else "noop")),
            "timestamp": time.time(),
            "summary": repr(transformed_op),
        })

        self.version += 1
        self.updated_at = time.time()

        # Check snapshot creation
        if self.version % self.SNAPSHOT_INTERVAL == 0:
            self.snapshots[self.version] = self.get_content()
            self.snapshots_formatting[self.version] = self.formatting.to_list()

        return transformed_op, self.version

    def add_user(self, user_id: str, user_name: str, color: str) -> UserState:
        user = UserState(user_id, user_name, color)
        self.active_users[user_id] = user
        return user

    def remove_user(self, user_id: str) -> Optional[UserState]:
        return self.active_users.pop(user_id, None)

    def update_cursor(self, user_id: str, cursor_pos: Dict[str, Any]) -> Optional[UserState]:
        if user_id in self.active_users:
            self.active_users[user_id].cursor_pos = cursor_pos
            self.active_users[user_id].last_active = time.time()
            return self.active_users[user_id]
        return None

    def get_users_list(self) -> List[Dict[str, Any]]:
        return [user.to_dict() for user in self.active_users.values()]

    def get_history_summary(self) -> List[Dict[str, Any]]:
        return self.history_metadata[-100:]  # Return last 100 changes

    def get_snapshot_at_version(self, target_version: int) -> Optional[str]:
        """Returns document content at a past version."""
        if target_version in self.snapshots:
            return self.snapshots[target_version]
        if target_version == self.version:
            return self.get_content()

        # Reconstruct from closest prior snapshot
        snapshot_versions = sorted([v for v in self.snapshots.keys() if v <= target_version])
        if not snapshot_versions:
            base_v = 0
            base_text = ""
            base_formatting: list = []
        else:
            base_v = snapshot_versions[-1]
            base_text = self.snapshots[base_v]
            base_formatting = self.snapshots_formatting.get(base_v, [])

        reconstructed_rope = Rope(base_text)
        reconstructed_formatting = FormattingStore(base_formatting)
        for i in range(base_v, target_version):
            op = self.history[i]
            if isinstance(op, InsertOp):
                pos = min(reconstructed_rope.length(), op.pos)
                reconstructed_rope.insert(pos, op.text)
                reconstructed_formatting.insert(pos, len(op.text))
            elif isinstance(op, DeleteOp):
                start = min(reconstructed_rope.length(), op.pos)
                end = min(reconstructed_rope.length(), start + op.length)
                reconstructed_rope.delete(start, end)
                reconstructed_formatting.delete(start, end)
            elif isinstance(op, FormatOp):
                if op.end > op.start:
                    reconstructed_formatting.format(op.start, op.end, op.attributes)

        content = reconstructed_rope.to_string()
        self.snapshots[target_version] = content
        return content

    def get_snapshot_formatting_at_version(self, target_version: int) -> list:
        """Reconstructs the formatting interval list at a past version."""
        snapshot_versions = sorted([v for v in self.snapshots_formatting.keys() if v <= target_version])
        if not snapshot_versions:
            base_v, base_formatting = 0, []
        else:
            base_v = snapshot_versions[-1]
            base_formatting = self.snapshots_formatting[base_v]

        reconstructed_formatting = FormattingStore(base_formatting)
        doc_length = max((e for _, e, _ in base_formatting), default=0)
        for i in range(base_v, target_version):
            op = self.history[i]
            if isinstance(op, InsertOp):
                reconstructed_formatting.insert(op.pos, len(op.text))
                doc_length += len(op.text)
            elif isinstance(op, DeleteOp):
                start = min(doc_length, op.pos)
                end = min(doc_length, start + op.length)
                reconstructed_formatting.delete(start, end)
                doc_length -= (end - start)
            elif isinstance(op, FormatOp):
                if op.end > op.start:
                    reconstructed_formatting.format(op.start, op.end, op.attributes)
        return reconstructed_formatting.to_list()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "docId": self.doc_id,
            "title": self.title,
            "content": self.get_content(),
            "markdown": self.get_markdown(),
            "version": self.version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "length": self.length(),
            "activeUserCount": len(self.active_users),
        }

    def save_to_file(self, directory: str) -> str:
        """Persists document state to a JSON file."""
        os.makedirs(directory, exist_ok=True)
        filepath = os.path.join(directory, f"{self.doc_id}.json")
        data = {
            "docId": self.doc_id,
            "title": self.title,
            "content": self.get_content(),
            "version": self.version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "history": [op.to_dict() for op in self.history],
            "historyMetadata": self.history_metadata,
            "snapshots": self.snapshots,
            "snapshotsFormatting": {
                str(k): v for k, v in self.snapshots_formatting.items()
            },
            "formatting": self.formatting.to_list(),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return filepath

    @classmethod
    def load_from_file(cls, filepath: str) -> 'Document':
        """Loads document state from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc = cls(
            doc_id=data["docId"],
            title=data.get("title", "Untitled Document"),
            initial_text=data.get("content", ""),
        )
        doc.version = data.get("version", 0)
        doc.created_at = data.get("createdAt", time.time())
        doc.updated_at = data.get("updatedAt", time.time())
        doc.history = [Operation.from_dict(d) for d in data.get("history", [])]
        doc.history_metadata = data.get("historyMetadata", [])
        doc.snapshots = {int(k): v for k, v in data.get("snapshots", {}).items()}
        doc.snapshots_formatting = {
            int(k): v for k, v in data.get("snapshotsFormatting", {}).items()
        }
        if not doc.snapshots_formatting:
            doc.snapshots_formatting = {0: []}
        doc.formatting = FormattingStore(data.get("formatting", []))
        return doc


class DocumentManager:
    """Manages all active documents and disk persistence."""

    def __init__(self, storage_dir: str = "data/documents"):
        self.storage_dir = storage_dir
        self.documents: Dict[str, Document] = {}
        self._load_existing_documents()

    def _load_existing_documents(self) -> None:
        """Loads any saved documents from disk on startup."""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir, exist_ok=True)
            return

        for filename in os.listdir(self.storage_dir):
            if filename.endswith(".json"):
                try:
                    filepath = os.path.join(self.storage_dir, filename)
                    doc = Document.load_from_file(filepath)
                    self.documents[doc.doc_id] = doc
                except Exception as e:
                    print(f"Error loading document {filename}: {e}")

    def get_or_create(
        self, doc_id: str, title: Optional[str] = None, initial_text: str = ""
    ) -> Document:
        """Retrieves an existing document or creates a new one."""
        if doc_id not in self.documents:
            default_title = title or f"Document {doc_id[:6]}"
            default_text = initial_text or (
                "Welcome to the Collaborative Real-Time Text Editor!\n\n"
                "Multiple users can edit this document at the same time.\n"
                "Features:\n"
                "• Balanced AVL Rope data structure for high performance\n"
                "• Operational Transformation (OT) for conflict-free real-time sync\n"
                "• Live multi-user cursors and selection presence\n"
                "• Full version history and snapshot time-travel\n"
                "• Local Undo/Redo support\n"
            ) if doc_id == "welcome" else ""
            
            self.documents[doc_id] = Document(
                doc_id=doc_id,
                title=default_title,
                initial_text=default_text,
            )
        return self.documents[doc_id]

    def list_documents(self) -> List[Dict[str, Any]]:
        """Returns metadata for all active/saved documents."""
        # Ensure welcome document exists
        self.get_or_create("welcome", "Welcome Guide")
        return [doc.to_dict() for doc in self.documents.values()]

    def create_document(
        self,
        doc_id: Optional[str] = None,
        title: Optional[str] = None,
        initial_content: Optional[str] = None,
        initial_formatting: Optional[list] = None,
    ) -> Document:
        """Creates a new document with an auto-generated id and returns it."""
        if not doc_id:
            doc_id = "doc-" + uuid.uuid4().hex[:8]
        doc_id = doc_id.strip()
        if doc_id in self.documents:
            raise ValueError(f"Document '{doc_id}' already exists")
        title = title or f"Document {doc_id[:8]}"
        doc = Document(
            doc_id=doc_id,
            title=title,
            initial_text=initial_content if initial_content is not None else "",
        )
        if initial_formatting:
            doc.formatting = FormattingStore(initial_formatting)
        self.documents[doc_id] = doc
        self.save_document(doc_id)
        return doc

    def rename_document(self, doc_id: str, new_title: str) -> Document:
        """Renames an existing document."""
        if doc_id not in self.documents:
            raise KeyError(f"Document '{doc_id}' not found")
        self.documents[doc_id].title = new_title
        self.documents[doc_id].updated_at = time.time()
        self.save_document(doc_id)
        return self.documents[doc_id]

    def delete_document(self, doc_id: str) -> None:
        """Deletes a document from memory and from disk."""
        if doc_id == "welcome":
            raise ValueError("The welcome document cannot be deleted")
        self.documents.pop(doc_id, None)
        filepath = os.path.join(self.storage_dir, f"{doc_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)

    def save_document(self, doc_id: str) -> Optional[str]:
        if doc_id in self.documents:
            return self.documents[doc_id].save_to_file(self.storage_dir)
        return None

    def save_all(self) -> None:
        for doc in self.documents.values():
            doc.save_to_file(self.storage_dir)

