# Synapse: Collaborative Real-Time Text Editor

A full-stack, real-time collaborative text editor built from scratch in Python and modern Web standards. Synapse delivers conflict-free simultaneous multi-user document editing, live cursor/selection awareness, **Rich Text formatting**, **Document Management (CRUD + Persistence)**, **Markdown/Plain-Text Export**, and **Version History with Snapshots**, engineered with an **AVL-balanced Rope** document model and **Operational Transformation (OT)** concurrency engine.

---

## 🌟 Key Features

- **Balanced AVL Rope Data Structure**: Documents are represented internally as balanced binary trees of character chunks, providing $O(\log N)$ time complexity for insertions, deletions, substrings, and character lookups even on large documents.
- **Operational Transformation (OT) Concurrency Engine**: Full TP1-compliant transformation function for concurrent `Insert`, `Delete`, and `Format` operations using the Jupiter client-server model. Guarantees deterministic convergence across all clients and the authoritative server.
- **Rich Text Formatting**: Live multi-user formatting for **Bold**, *Italic*, <u>Underline</u>, Headings (`# H1`, `## H2`, `### H3`), Blockquotes (`>`), and Inline Code (`` `code` ``) synchronized in real time with attribute range transformations.
- **Document Management & Persistence**: Complete REST API (`GET`, `POST`, `PUT`, `DELETE /api/documents`) and interactive dashboard to create, open, rename, delete, and search documents with automatic disk persistence across restarts.
- **Multi-Format Export**: One-click client and REST endpoint export to **Markdown (`.md`)**, **Plain Text (`.txt`)**, and **Document JSON (`.json`)**.
- **Live Cursor & Presence Awareness**: Smoothly renders remote user carets, author name tags, and active text selection ranges with distinct user-chosen colors.
- **Version History & Snapshot Time-Travel**: Automatic snapshotting every 10 operations, history inspection drawer, and one-click version rollback (client-side, stored in document JSON).
- **Local Undo / Redo**: Operation inversion stack allowing each user to undo their own local text and formatting changes without discarding remote peer edits (using OT-aware selective undo).
- **Self-Contained Single-Command Server**: Serves both static frontend assets, REST APIs, and WebSocket endpoints from a single Python `aiohttp` process on `http://localhost:8000`.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Browser Client 1 (Alice)
        UI1[Rich Editor UI & Toolbar]
        Diff1[Diffing & Format Engine]
        OT1[Client OT State Machine]
        WS1[WebSocket Client]
        CM1[Cursor & Presence Manager]
    end

    subgraph Browser Client 2 (Bob)
        UI2[Rich Editor UI & Toolbar]
        Diff2[Diffing & Format Engine]
        OT2[Client OT State Machine]
        WS2[WebSocket Client]
        CM2[Cursor & Presence Manager]
    end

    subgraph Python Backend Server (aiohttp)
        REST[REST API /api/documents]
        WSServer[WebSocket Hub /ws]
        DocMgr[Document Manager]
        ServerOT[OT Concurrency Engine]
        RopeModel[AVL-Balanced Rope Tree]
        FmtStore[Formatting Interval Store]
        DiskStorage[(data/documents/*.json)]
    end

    UI1 -->|Typing & Formatting| Diff1
    Diff1 -->|Local Op| OT1
    OT1 -->|Send Op (Base Version)| WS1
    WS1 <-->|WebSocket JSON| WSServer

    UI2 -->|Typing & Formatting| Diff2
    Diff2 -->|Local Op| OT2
    OT2 -->|Send Op (Base Version)| WS2
    WS2 <-->|WebSocket JSON| WSServer

    REST <--> DocMgr
    WSServer <--> DocMgr
    DocMgr --> ServerOT
    ServerOT -->|Transformed Text Op| RopeModel
    ServerOT -->|Transformed Format Op| FmtStore
    DocMgr -->|Auto-save / Reload| DiskStorage
    WSServer -->|Broadcast Transformed Ops & Cursors| WS1
    WSServer -->|Broadcast Transformed Ops & Cursors| WS2

## 📚 REST API Specification

| Method | Endpoint | Request Body | Response | Description |
|---|---|---|---|---|
| `GET` | `/api/documents` | None | `{"documents": [...]}` | List all documents with metadata & last modified |
| `POST` | `/api/documents` | `{"title": "My Doc"}` *(optional)* | `{"document": {...}}` (201) | Create a new document with generated/custom ID |
| `GET` | `/api/documents/:id` | None | `{"document": {...}}` | Retrieve document metadata and content |
| `PUT` | `/api/documents/:id` | `{"title": "New Title"}` | `{"document": {...}}` | Rename an existing document |
| `DELETE`| `/api/documents/:id` | None | `{"deleted": true, "docId": "..."}` | Delete document from memory and disk |
| `GET` | `/api/documents/:id/export?format=markdown\|text` | None | Downloaded file stream | Export document as Markdown or Plain Text |

---

## 🧠 Core Algorithms & Technical Design

### 1. Document Representation: AVL-Balanced Rope (`backend/rope.py`)

A **Rope** is a binary tree where leaf nodes hold character strings of at most `MAX_LEAF_LEN = 256` characters, and internal nodes store the `weight` (length of left subtree) and subtree `height`.

```
              Node(weight=12, height=3)
             /                         \
    Node(weight=6, height=2)        Leaf(" World!", len=7)
    /                      \
Leaf("Hello ", len=6)   Leaf("there,", len=6)
```

- **`insert(position, text)`**: Splits the tree at `position` in $O(\log N)$ time into $L$ and $R$, constructs a new balanced tree from `text`, concatenates $L + \text{new\_tree} + R$, and rebalances with AVL rotations.
- **`delete(start, end)`**: Splits at `end` into $L_1$ and $R_1$, splits $L_1$ at `start` into $L_2$ and $D$, and concatenates $L_2 + R_1$.
- **AVL Spine-Descent Concatenation**: When concatenating trees with height difference $|h_1 - h_2| > 1$, the concatenation algorithm descends along the spine to attach at the appropriate height and applies single/double AVL rotations on the return path, maintaining balance factor $|BF| \le 1$.

### 2. Rich Text Formatting Store (`backend/formatting.py`)

Formatting is represented as non-overlapping/merged character intervals:
```python
[[0, 11, {"bold": True}], [5, 17, {"italic": True}], [0, 20, {"header": 1}]]
```
- **Text-Shift Invariance**: When an `insert(pos, len)` occurs, intervals $\ge pos$ are shifted right by $len$. When a `delete(start, end)` occurs, intervals are clipped and shifted left.
- **`format(start, end, attributes)`**: Sets or clears attributes on $[start, end)$, splitting and merging intervals as needed.
- **`to_markdown(text)`**: Converts the formatted character stream into standard Markdown:
  - Bold $\to$ `**text**`
  - Italic $\to$ `*text*`
  - Underline $\to$ `<u>text</u>`
  - Headings $\to$ `# Heading 1`, `## Heading 2`, `### Heading 3`
  - Blockquotes $\to$ `> quote`
  - Code $\to$ `` `code` ``

### 3. Concurrency Control: Operational Transformation (OT) (`backend/ot.py`)

Synapse satisfies **Transformation Property 1 (TP1)** across text and formatting operations:
$$S \circ O_1 \circ T(O_2, O_1)_1 = S \circ O_2 \circ T(O_1, O_2)_1$$

| Case | Transformation Rule |
|---|---|
| **Insert vs Insert** | If $pos_1 < pos_2$, $pos_2' = pos_2 + |text_1|$; if $pos_1 == pos_2$, tie-break deterministically using user IDs. |
| **Insert vs Delete** | If insert is before delete, delete shifts right; if insert is after delete, insert shifts left; if insert is strictly inside delete range, insert resolves to `NoOp` and delete encompasses text. |
| **Delete vs Delete** | Disjoint deletes shift index by deleted length; overlapping deletes compute non-overlapping segments and reduce lengths. |
| **Text vs Format** | When an insert or delete occurs before a format range, the format range is shifted/trimmed accordingly. |
| **Format vs Format** | Overlapping format operations are merged deterministically using tie-breaking on `op_id`. |

---

## 🚀 Quick Start & Running Locally

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the Server
Run with a single command:
```bash
python run.py
```
*(Optionally specify `--port 8000` or `--host 0.0.0.0`)*

### 3. Open in Browser
Open your browser and navigate to:
```
http://localhost:8000
```

### 4. Multi-User Testing
1. Open **two or more separate browser tabs** or an incognito window at `http://localhost:8000`.
2. Choose different names and colors in each tab.
3. Create or join the same document ID (e.g. `welcome` or create a new document).
4. Select text and click **Bold**, *Italic*, <u>Underline</u>, or **Heading 1** in one tab — watch the formatting and cursor render simultaneously in the other tab!
5. Try renaming and deleting documents from the Library dashboard.
6. Click **Export** in the toolbar to download the document as **Markdown (`.md`)** or **Plain Text (`.txt`)**.

---

## 🧪 Running Automated Tests

Run the full automated test suite (36 tests covering Rope AVL rebalancing, OT mathematical properties, Document CRUD, Formatting synchronization, and Multi-Client WebSockets):

```bash
python -m unittest discover backend/tests
```

Individual test suites:
- **Rope Data Structure & AVL Rebalancing Tests**:
  ```bash
  python -m unittest backend/tests/test_rope.py
  ```
- **Operational Transformation TP1 Tests**:
  ```bash
  python -m unittest backend/tests/test_ot.py
  ```
- **Document CRUD, Persistence & REST API Tests**:
  ```bash
  python -m unittest backend/tests/test_documents.py
  ```
- **Rich Text Formatting Interval Tests**:
  ```bash
  python -m unittest backend/tests/test_formatting.py
  ```
- **Asynchronous Multi-Client Integration Tests**:
  ```bash
  python -m unittest backend/tests/test_integration.py
  ```

---

## 📁 Project Structure

```
collaborative-editor/
├── backend/
│   ├── __init__.py
│   ├── rope.py              # AVL-balanced Rope data structure
│   ├── formatting.py        # Rich text interval store & Markdown exporter
│   ├── ot.py                # Operational Transformation engine (TP1, invert, transform)
│   ├── document_manager.py  # Document state, version history, snapshots, disk persistence
│   ├── server.py            # Unified aiohttp HTTP + WebSocket server
│   └── tests/
│       ├── __init__.py
│       ├── test_rope.py     # Unit & 500-step randomized fuzz tests for Rope
│       ├── test_ot.py       # TP1 mathematical property and concurrency tests
│       ├── test_formatting.py # Formatting interval store and Markdown rendering tests
│       ├── test_documents.py# REST CRUD and persistence tests
│       └── test_integration.py # Multi-client simulated async integration tests
├── frontend/
│   ├── index.html           # Single-page app layout (lobby, editor, history drawer, modals)
│   ├── style.css            # Modern Google Docs-inspired theme, rich toolbar & cursor overlays
│   └── js/
│       ├── ws_client.js     # WebSocket connection manager with heartbeat & auto-reconnect
│       ├── ot_client.js     # Client OT state machine & text diffing engine
│       ├── cursor_manager.js# Measurement mirror & remote cursor/selection renderer
│       └── app.js           # Main application controller with rich formatting & CRUD
├── data/
│   └── documents/           # Directory for auto-saved JSON document snapshots
├── run.py                   # Single-command launcher script
├── requirements.txt         # Dependencies (aiohttp, websockets)
├── .gitignore               # Git ignore patterns
└── README.md                # Project documentation
```
