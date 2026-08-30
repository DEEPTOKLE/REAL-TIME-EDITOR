/**
 * Synapse Real-Time Collaborative Editor - Main Application Controller
 * Features:
 * - Real-Time Collaborative Editing with AVL Rope & Operational Transformation
 * - Full Document Management (CRUD, Search, Persistence)
 * - Rich Text Formatting (Bold, Italic, Underline, Headings H1/H2/H3, Quote, Code, Clear)
 * - Multi-format Export (Markdown, Plain Text, Document JSON)
 * - Real-time Cursor & Presence Awareness
 * - Version History Timeline & Snapshot Time-Travel
 */

(function () {
  "use strict";

  // Palette of Distinct Collaborator Colors
  const USER_COLORS = [
    "#1a73e8", // Google Blue
    "#d93025", // Red
    "#1e8e3e", // Green
    "#f9ab00", // Yellow / Amber
    "#9334e9", // Purple
    "#e37400", // Orange
    "#12b5cb", // Cyan
    "#e52592", // Magenta
  ];

  class App {
    constructor() {
      // User Profile State
      this.userId = localStorage.getItem("synapse_userId") || this.generateId(8);
      this.userName = localStorage.getItem("synapse_userName") || this.generateRandomName();
      this.userColor = localStorage.getItem("synapse_userColor") || USER_COLORS[Math.floor(Math.random() * USER_COLORS.length)];

      localStorage.setItem("synapse_userId", this.userId);
      localStorage.setItem("synapse_userName", this.userName);
      localStorage.setItem("synapse_userColor", this.userColor);

      this.currentDocId = null;
      this.currentDocTitle = "Untitled Document";
      this.lastEditorText = "";
      this.cursorDebounceTimer = null;
      this.previewingVersion = null;
      this.isPreviewing = false;
      this.savedSelStart = 0;
      this.savedSelEnd = 0;

      // Formatting State: List of [start, end, {attr: val}]
      this.formattingIntervals = [];
      this.allDocuments = [];

      // DOM Elements
      this.dom = {
        lobbyView: document.getElementById("lobby-view"),
        editorView: document.getElementById("editor-view"),
        userNameInput: document.getElementById("user-name-input"),
        colorSwatches: document.getElementById("color-swatches"),
        newDocTitle: document.getElementById("new-doc-title"),
        btnCreateDoc: document.getElementById("btn-create-doc"),
        joinDocId: document.getElementById("join-doc-id"),
        btnJoinDoc: document.getElementById("btn-join-doc"),
        documentsGrid: document.getElementById("documents-grid"),
        btnRefreshDocs: document.getElementById("btn-refresh-docs"),
        searchDocsInput: document.getElementById("search-docs-input"),
        docCountBadge: document.getElementById("doc-count-badge"),

        // Editor Top Nav
        btnBackLobby: document.getElementById("btn-back-lobby"),
        docTitleInput: document.getElementById("doc-title-input"),
        docIdBadge: document.getElementById("doc-id-badge"),
        activeUsersList: document.getElementById("active-users-list"),
        connectionStatus: document.getElementById("connection-status"),
        pingIndicator: document.getElementById("ping-indicator"),
        btnShareDoc: document.getElementById("btn-share-doc"),
        btnToggleTheme: document.getElementById("btn-toggle-theme"),

        // Editor Toolbar
        btnUndo: document.getElementById("btn-undo"),
        btnRedo: document.getElementById("btn-redo"),
        fontFamilySelect: document.getElementById("font-family-select"),
        fontSizeSelect: document.getElementById("font-size-select"),
        btnVersionHistory: document.getElementById("btn-version-history"),
        btnExportMenu: document.getElementById("btn-export-menu"),
        exportDropdown: document.getElementById("export-dropdown"),
        syncStatusText: document.getElementById("sync-status-text"),

        // Rich Formatting Buttons
        btnFormatBold: document.getElementById("btn-format-bold"),
        btnFormatItalic: document.getElementById("btn-format-italic"),
        btnFormatUnderline: document.getElementById("btn-format-underline"),
        btnFormatH1: document.getElementById("btn-format-h1"),
        btnFormatH2: document.getElementById("btn-format-h2"),
        btnFormatH3: document.getElementById("btn-format-h3"),
        btnFormatQuote: document.getElementById("btn-format-quote"),
        btnFormatCode: document.getElementById("btn-format-code"),
        btnFormatClear: document.getElementById("btn-format-clear"),

        // Paper Surface
        editorGutter: document.getElementById("editor-gutter"),
        editorTextarea: document.getElementById("editor-textarea"),
        formattedBackdrop: document.getElementById("formatted-backdrop"),
        remoteOverlay: document.getElementById("remote-overlay"),

        // Statusbar
        statVersion: document.getElementById("stat-version"),
        statUsers: document.getElementById("stat-users"),
        statSaveStatus: document.getElementById("stat-save-status"),
        statCursor: document.getElementById("stat-cursor"),
        statWords: document.getElementById("stat-words"),
        statChars: document.getElementById("stat-chars"),

        // History Drawer
        historyDrawer: document.getElementById("history-drawer"),
        btnCloseHistory: document.getElementById("btn-close-history"),
        historyPreviewBanner: document.getElementById("history-preview-banner"),
        previewVersionNum: document.getElementById("preview-version-num"),
        btnRestoreVersion: document.getElementById("btn-restore-version"),
        historyTimelineList: document.getElementById("history-timeline-list"),

        // Modals
        renameModal: document.getElementById("rename-modal"),
        renameDocId: document.getElementById("rename-doc-id"),
        renameDocTitle: document.getElementById("rename-doc-title"),
        btnConfirmRename: document.getElementById("btn-confirm-rename"),

        deleteModal: document.getElementById("delete-modal"),
        deleteDocId: document.getElementById("delete-doc-id"),
        deleteDocName: document.getElementById("delete-doc-name"),
        btnConfirmDelete: document.getElementById("btn-confirm-delete"),

        // Toast Container
        toastContainer: document.getElementById("toast-container"),
      };

      // Initialize Subsystems
      this.ws = new WebSocketClient("/ws");
      this.ot = new OTClient(
        this.userId,
        (op) => this.applyRemoteOperation(op),
        (op, version) => this.sendOperationToServer(op, version)
      );
      this.cursorManager = new CursorManager(this.dom.editorTextarea, this.dom.remoteOverlay);

      this.isOnline = true;
      this.offlineQueue = [];
      this.selectedImagePos = null;
      this.resizeDragState = null;

      this.initTheme();
      this.initProfileUI();
      this.bindEvents();
      this.initImport();
      this.initImageResize();
      this.bindWebSocketEvents();
      this.checkUrlForDocument();
      this.fetchRecentDocuments();
    }

    generateId(length = 8) {
      return Math.random().toString(36).substring(2, 2 + length);
    }

    generateRandomName() {
      const adjectives = ["Clever", "Swift", "Bright", "Curious", "Creative", "Stellar", "Noble", "Eager"];
      const nouns = ["Panda", "Fox", "Falcon", "Otter", "Dolphin", "Cheetah", "Owl", "Badger"];
      const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
      const noun = nouns[Math.floor(Math.random() * nouns.length)];
      return `${adj} ${noun}`;
    }

    // -------------------------------------------------------------------------
    // Theme & Profile UI
    // -------------------------------------------------------------------------

    initTheme() {
      const savedTheme = localStorage.getItem("synapse_theme") || "theme-light";
      document.body.className = savedTheme;
    }

    toggleTheme() {
      const isDark = document.body.classList.contains("theme-dark");
      const nextTheme = isDark ? "theme-light" : "theme-dark";
      document.body.className = nextTheme;
      localStorage.setItem("synapse_theme", nextTheme);
    }

    initProfileUI() {
      this.dom.userNameInput.value = this.userName;
      this.dom.colorSwatches.innerHTML = "";

      USER_COLORS.forEach((color) => {
        const swatch = document.createElement("button");
        swatch.className = `color-swatch ${color === this.userColor ? "active" : ""}`;
        swatch.style.backgroundColor = color;
        swatch.title = color;
        swatch.addEventListener("click", () => {
          this.userColor = color;
          localStorage.setItem("synapse_userColor", color);
          document.querySelectorAll(".color-swatch").forEach((s) => s.classList.remove("active"));
          swatch.classList.add("active");
          this.broadcastCursor();
        });
        this.dom.colorSwatches.appendChild(swatch);
      });

      this.dom.userNameInput.addEventListener("input", (e) => {
        this.userName = e.target.value.trim() || "Collaborator";
        localStorage.setItem("synapse_userName", this.userName);
      });
    }

    // -------------------------------------------------------------------------
    // Document Management (CRUD & REST API)
    // -------------------------------------------------------------------------

    checkUrlForDocument() {
      const params = new URLSearchParams(window.location.search);
      const docParam = params.get("doc") || params.get("docId");
      if (docParam) {
        this.joinDocument(docParam);
      }
    }

    switchView(viewName) {
      if (viewName === "editor") {
        this.dom.lobbyView.classList.remove("active");
        this.dom.editorView.classList.add("active");
      } else {
        this.dom.editorView.classList.remove("active");
        this.dom.lobbyView.classList.add("active");
        this.currentDocId = null;
        this.ws.disconnect();
        this.offlineQueue = [];
        this.isOnline = true;
        this.updateOfflineBanner(false);
        window.history.pushState({}, "", window.location.pathname);
        this.fetchRecentDocuments();
      }
    }

    joinDocument(docId, initialTitle = null) {
      if (!docId) return;
      this.currentDocId = docId.trim();
      this.currentDocTitle = initialTitle || `Document ${this.currentDocId}`;

      this.dom.docIdBadge.textContent = this.currentDocId;
      this.dom.docTitleInput.value = this.currentDocTitle;

      const newUrl = `${window.location.pathname}?doc=${encodeURIComponent(this.currentDocId)}`;
      window.history.pushState({ doc: this.currentDocId }, "", newUrl);

      this.switchView("editor");

      // Connect to WebSocket server
      this.ws.connect(this.currentDocId, {
        userId: this.userId,
        userName: this.userName,
        color: this.userColor,
      });
    }

    async fetchRecentDocuments() {
      try {
        const resp = await fetch("/api/documents");
        if (resp.ok) {
          const data = await resp.json();
          this.allDocuments = data.documents || [];
          this.filterAndRenderDocuments();
        }
      } catch (err) {
        console.error("Error loading document list:", err);
      }
    }

    filterAndRenderDocuments() {
      const query = (this.dom.searchDocsInput.value || "").toLowerCase().trim();
      const filtered = this.allDocuments.filter((d) => {
        const title = (d.title || "").toLowerCase();
        const id = (d.docId || "").toLowerCase();
        return title.includes(query) || id.includes(query);
      });
      this.renderRecentDocuments(filtered);
    }

    renderRecentDocuments(docs) {
      this.dom.documentsGrid.innerHTML = "";
      this.dom.docCountBadge.textContent = docs.length;

      if (docs.length === 0) {
        this.dom.documentsGrid.innerHTML = `
          <div class="empty-docs-msg" style="color: var(--text-muted); font-size: 14px; grid-column: 1/-1; padding: 24px; text-align: center;">
            No documents found. Create one above to start collaborating!
          </div>
        `;
        return;
      }

      docs.forEach((doc) => {
        const card = document.createElement("div");
        card.className = "doc-card";

        const previewText = doc.content ? doc.content.substring(0, 140) : "Blank document...";
        const userCount = doc.activeUserCount || 0;
        const updatedDate = doc.updatedAt ? new Date(doc.updatedAt * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Recently";

        card.innerHTML = `
          <div class="doc-card-header">
            <div class="doc-card-title" title="Open ${this.escapeHtml(doc.title || doc.docId)}">${this.escapeHtml(doc.title || doc.docId)}</div>
            <div class="doc-card-actions">
              <button class="btn-icon btn-rename-card" title="Rename Document">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
              </button>
              ${
                doc.docId !== "welcome"
                  ? `<button class="btn-icon danger btn-delete-card" title="Delete Document">
                       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                     </button>`
                  : ""
              }
            </div>
          </div>
          <p class="doc-card-preview">${this.escapeHtml(previewText)}</p>
          <div class="doc-card-meta">
            <div class="doc-card-meta-left">
              <span>v${doc.version || 0}</span>
              <span class="dot-separator">•</span>
              <span>${updatedDate}</span>
            </div>
            ${
              userCount > 0
                ? `<span style="color: var(--accent-success); font-weight: 600; display: flex; align-items: center; gap: 4px;">
                     <svg style="width:12px; height:12px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="7" r="4"></circle><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path></svg>
                     ${userCount} active
                   </span>`
                : `<span style="font-family: var(--font-mono); font-size: 11px;">ID: ${this.escapeHtml(doc.docId)}</span>`
            }
          </div>
        `;

        // Click on title or preview opens document
        card.querySelector(".doc-card-title").addEventListener("click", () => this.joinDocument(doc.docId, doc.title));
        card.querySelector(".doc-card-preview").addEventListener("click", () => this.joinDocument(doc.docId, doc.title));

        // Rename button
        card.querySelector(".btn-rename-card").addEventListener("click", (e) => {
          e.stopPropagation();
          this.openRenameModal(doc.docId, doc.title || doc.docId);
        });

        // Delete button
        const delBtn = card.querySelector(".btn-delete-card");
        if (delBtn) {
          delBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            this.openDeleteModal(doc.docId, doc.title || doc.docId);
          });
        }

        this.dom.documentsGrid.appendChild(card);
      });
    }

    async createDocument(title = "") {
      try {
        const resp = await fetch("/api/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: title.trim() || undefined }),
        });
        if (resp.ok) {
          const data = await resp.json();
          this.joinDocument(data.document.docId, data.document.title);
          this.showToast(`Document "${data.document.title}" created`);
        } else {
          this.showToast("Failed to create document");
        }
      } catch (err) {
        console.error("Error creating document:", err);
        const docId = "doc-" + this.generateId(6);
        this.joinDocument(docId, title || "Untitled Document");
      }
    }

    openRenameModal(docId, currentTitle) {
      this.dom.renameDocId.value = docId;
      this.dom.renameDocTitle.value = currentTitle;
      this.dom.renameModal.classList.add("open");
      setTimeout(() => this.dom.renameDocTitle.focus(), 100);
    }

    async confirmRename() {
      const docId = this.dom.renameDocId.value;
      const newTitle = this.dom.renameDocTitle.value.trim();
      if (!newTitle) return;

      try {
        const resp = await fetch(`/api/documents/${encodeURIComponent(docId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: newTitle }),
        });
        if (resp.ok) {
          if (this.currentDocId === docId) {
            this.currentDocTitle = newTitle;
            this.dom.docTitleInput.value = newTitle;
          }
          this.closeModals();
          this.fetchRecentDocuments();
          this.showToast(`Document renamed to "${newTitle}"`);
        }
      } catch (err) {
        console.error("Error renaming document:", err);
      }
    }

    openDeleteModal(docId, title) {
      this.dom.deleteDocId.value = docId;
      this.dom.deleteDocName.textContent = `"${title}"`;
      this.dom.deleteModal.classList.add("open");
    }

    async confirmDelete() {
      const docId = this.dom.deleteDocId.value;
      if (!docId) return;

      try {
        const resp = await fetch(`/api/documents/${encodeURIComponent(docId)}`, {
          method: "DELETE",
        });
        if (resp.ok) {
          this.closeModals();
          this.fetchRecentDocuments();
          this.showToast("Document deleted successfully");
          if (this.currentDocId === docId) {
            this.switchView("lobby");
          }
        }
      } catch (err) {
        console.error("Error deleting document:", err);
      }
    }

    closeModals() {
      document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("open"));
    }

    escapeHtml(str) {
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    // -------------------------------------------------------------------------
    // WebSocket Event Handlers
    // -------------------------------------------------------------------------
    bindWebSocketEvents() {

      this.ws.on("status_change", ({ status, message }) => {
        this.dom.connectionStatus.className =
          `connection-badge ${status}`;
        const statusLabel =
          this.dom.connectionStatus.querySelector(".status-text");

        if (status === "connected") {
          const wasOffline = !this.isOnline;
          this.isOnline = true;
          statusLabel.textContent = "Connected";
          this.dom.statSaveStatus.textContent = "Saved";
          this.updateOfflineBanner(false);

          if (wasOffline) {
            setTimeout(() => this.flushOfflineQueue(), 600);
          }
        } else if (status === "syncing") {
          this.isOnline = false;
          statusLabel.textContent = message || "Syncing...";
          this.dom.statSaveStatus.textContent = "Syncing...";
          this.updateOfflineBanner(true);
        } else {
          this.isOnline = false;
          statusLabel.textContent = "Disconnected";
          this.dom.statSaveStatus.textContent = "Offline";
          this.updateOfflineBanner(true);
        }
      });

      this.ws.on("latency_update", (latency) => {
        this.dom.pingIndicator.textContent = `~${latency}ms`;
      });

      // Initial Document State Packet
      this.ws.on("init", (data) => {
        this.currentDocTitle = data.title || `Document ${data.docId}`;
        this.dom.docTitleInput.value = this.currentDocTitle;
        this.ot.reset();
        this.ot.setVersion(data.version || 0);

        this.lastEditorText = data.content || "";
        this.formattingIntervals = data.formatting || [];
        this.dom.editorTextarea.value = this.lastEditorText;

        this.renderFormattedBackdrop();
        this.updateLineNumbers();
        this.updateStatistics();
        this.updateUndoRedoUI();

        if (data.users) {
          const peers = data.users.filter((u) => u.userId !== this.userId);
          this.cursorManager.setUsers(peers);
          this.renderActiveUserAvatars(data.users);
        }

        this.showToast(`Joined document "${this.currentDocTitle}"`);
      });

      // New peer joined
      this.ws.on("user_joined", (data) => {
        if (data.user && data.user.userId !== this.userId) {
          this.cursorManager.updateUser(data.user.userId, data.user);
          this.showToast(`${data.user.userName || "A user"} joined`);
        }
        if (data.activeUsers) {
          this.renderActiveUserAvatars(data.activeUsers);
        }
      });

      // Peer left
      this.ws.on("user_left", (data) => {
        if (data.userId) {
          this.cursorManager.removeUser(data.userId);
        }
        if (data.activeUsers) {
          this.renderActiveUserAvatars(data.activeUsers);
        }
      });

      // Server Ack for client operation
      this.ws.on("ack", (data) => {
        this.ot.handleServerAck(data.opId, data.version);
        this.dom.statVersion.innerHTML = `Version: <strong>${data.version}</strong>`;
        this.dom.statSaveStatus.textContent = "Saved";
        this.updateUndoRedoUI();
      });

      // Remote operation broadcast from peer
      this.ws.on("operation", (data) => {
        if (data.userId !== this.userId && data.op) {
          this.ot.handleRemoteOperation(data.op, data.version);
          this.dom.statVersion.innerHTML = `Version: <strong>${data.version}</strong>`;
        }
      });

      // Peer cursor update
      this.ws.on("cursor", (data) => {
        if (data.userId !== this.userId && data.cursor) {
          this.cursorManager.updateUserCursor(data.userId, data.cursor);
        }
      });

      // Document rename from peer or server
      this.ws.on("document_renamed", (data) => {
        if (data.docId === this.currentDocId && data.document) {
          this.currentDocTitle = data.document.title;
          this.dom.docTitleInput.value = data.document.title;
          this.showToast(`Document renamed to "${data.document.title}"`);
        }
      });

      // Full reset sync (e.g. version restore)
      this.ws.on("reset_sync", (data) => {
        this.ot.setVersion(data.version);
        this.lastEditorText = data.content;
        this.formattingIntervals = data.formatting || [];
        this.dom.editorTextarea.value = data.content;
        this.renderFormattedBackdrop();
        this.updateLineNumbers();
        this.updateStatistics();
        this.showToast(data.message || "Document synchronized");
      });

      // History list
      this.ws.on("history_list", (data) => {
        this.renderVersionHistoryTimeline(data.history || [], data.snapshots || []);
      });

      // Snapshot content preview
      this.ws.on("snapshot_content", (data) => {
        this.previewSnapshot(data.version, data.content, data.formatting);
      });
    }

    renderActiveUserAvatars(users) {
      this.dom.activeUsersList.innerHTML = "";
      this.dom.statUsers.innerHTML = `Active Users: <strong>${users.length}</strong>`;

      users.forEach((user) => {
        const isSelf = user.userId === this.userId;
        const avatar = document.createElement("div");
        avatar.className = "user-avatar";
        avatar.style.backgroundColor = user.color || "#1a73e8";
        avatar.title = `${user.userName}${isSelf ? " (You)" : ""}`;

        const initials = (user.userName || "U")
          .split(" ")
          .map((n) => n[0])
          .join("")
          .substring(0, 2)
          .toUpperCase();
        avatar.textContent = initials;

        this.dom.activeUsersList.appendChild(avatar);
      });
    }

    // -------------------------------------------------------------------------
    // Editor Real-Time Interaction, Rich Text Formatting & OT
    // -------------------------------------------------------------------------

    bindEvents() {
      // Lobby Actions
      this.dom.btnCreateDoc.addEventListener("click", () => {
        const title = this.dom.newDocTitle.value.trim();
        this.createDocument(title);
      });

      this.dom.btnJoinDoc.addEventListener("click", () => {
        const docId = this.dom.joinDocId.value.trim();
        if (docId) {
          this.joinDocument(docId);
        } else {
          this.showToast("Please enter a valid Document ID");
        }
      });

      this.dom.searchDocsInput.addEventListener("input", () => {
        this.filterAndRenderDocuments();
      });

      this.dom.btnRefreshDocs.addEventListener("click", () => {
        this.fetchRecentDocuments();
        this.showToast("Document list refreshed");
      });

      this.dom.btnBackLobby.addEventListener("click", () => {
        this.switchView("lobby");
      });

      this.dom.btnToggleTheme.addEventListener("click", () => {
        this.toggleTheme();
      });

      this.dom.btnShareDoc.addEventListener("click", () => {
        const url = window.location.href;
        navigator.clipboard.writeText(url).then(() => {
          this.showToast("Document link copied to clipboard!");
        });
      });

      this.dom.docIdBadge.addEventListener("click", () => {
        navigator.clipboard.writeText(this.currentDocId).then(() => {
          this.showToast(`Document ID "${this.currentDocId}" copied!`);
        });
      });

      // Document Title Rename inside Editor
      this.dom.docTitleInput.addEventListener("change", async (e) => {
        const newTitle = e.target.value.trim();
        if (newTitle && newTitle !== this.currentDocTitle) {
          try {
            await fetch(`/api/documents/${encodeURIComponent(this.currentDocId)}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ title: newTitle }),
            });
            this.currentDocTitle = newTitle;
            this.showToast("Document title saved");
          } catch (err) {
            console.error("Error updating title:", err);
          }
        }
      });

      // Textarea User Input Event
      this.dom.editorTextarea.addEventListener("input", () => {
        this.handleLocalInput();
      });

      // Cursor / Selection Change Events
      this.dom.editorTextarea.addEventListener("keyup", () => this.handleCursorMove());
      this.dom.editorTextarea.addEventListener("click", () => this.handleCursorMove());
      this.dom.editorTextarea.addEventListener("select", () => this.handleCursorMove());
      this.dom.editorTextarea.addEventListener("scroll", () => {
        if (this.dom.formattedBackdrop) {
          this.dom.formattedBackdrop.scrollTop = this.dom.editorTextarea.scrollTop;
        }
      });

      // Toolbar Undo / Redo
      this.dom.btnUndo.addEventListener("mousedown", (e) => e.preventDefault());
      this.dom.btnUndo.addEventListener("click", () => this.executeUndo());
      this.dom.btnRedo.addEventListener("mousedown", (e) => e.preventDefault());
      this.dom.btnRedo.addEventListener("click", () => this.executeRedo());

      // Rich Text Formatting Buttons
      const formatButtons = [
        { btn: this.dom.btnFormatBold, attr: "bold", val: true },
        { btn: this.dom.btnFormatItalic, attr: "italic", val: true },
        { btn: this.dom.btnFormatUnderline, attr: "underline", val: true },
        { btn: this.dom.btnFormatH1, attr: "header", val: 1 },
        { btn: this.dom.btnFormatH2, attr: "header", val: 2 },
        { btn: this.dom.btnFormatH3, attr: "header", val: 3 },
        { btn: this.dom.btnFormatQuote, attr: "blockquote", val: true },
        { btn: this.dom.btnFormatCode, attr: "code", val: true },
        { btn: this.dom.btnFormatClear, attr: "clear", val: true },
      ];

      formatButtons.forEach(({ btn, attr, val }) => {
        if (btn) {
          btn.addEventListener("mousedown", (e) => e.preventDefault());
          btn.addEventListener("click", () => this.applyFormat(attr, val));
        }
      });

      // Image Insert Button
      const imageFileInput = document.getElementById("image-file-input");
      if (imageFileInput) {
        imageFileInput.addEventListener("change", async (e) => {
          const file = e.target.files[0];
          if (!file) return;
          imageFileInput.value = "";

          try {
            this.showToast("Uploading image...");
            const { imgId } = await this.uploadImage(file);

            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
              URL.revokeObjectURL(url);
              this.insertImageAtCursor(imgId, img.naturalWidth, img.naturalHeight);
            };
            img.onerror = () => {
              URL.revokeObjectURL(url);
              this.showToast("Failed to read image dimensions");
            };
            img.src = url;
          } catch (err) {
            this.showToast(err.message || "Image upload failed");
          }
        });
      }

      // Keyboard Shortcuts for Undo, Redo, and Rich Formatting
      this.dom.editorTextarea.addEventListener("keydown", (e) => {
        // Delete the currently selected image instead of editing text.
        if ((e.key === "Delete" || e.key === "Backspace") && this.selectedImagePos !== null) {
          e.preventDefault();
          this.deleteSelectedImage();
          return;
        }

        const isMac = navigator.platform.toUpperCase().indexOf("MAC") >= 0;
        const modKey = isMac ? e.metaKey : e.ctrlKey;

        if (modKey && e.key.toLowerCase() === "z") {
          e.preventDefault();
          if (e.shiftKey) {
            this.executeRedo();
          } else {
            this.executeUndo();
          }
        } else if (modKey && e.key.toLowerCase() === "y" && !isMac) {
          e.preventDefault();
          this.executeRedo();
        } else if (modKey && e.key.toLowerCase() === "b") {
          e.preventDefault();
          this.applyFormat("bold", true);
        } else if (modKey && e.key.toLowerCase() === "i") {
          e.preventDefault();
          this.applyFormat("italic", true);
        } else if (modKey && e.key.toLowerCase() === "u") {
          e.preventDefault();
          this.applyFormat("underline", true);
        } else if (e.key === "Tab") {
          e.preventDefault();
          this.insertTextAtCursor("  ");
        }
      });

      // Font Family & Size
      this.dom.fontFamilySelect.addEventListener("change", (e) => {
        this.dom.editorTextarea.style.fontFamily = e.target.value;
        if (this.dom.formattedBackdrop) this.dom.formattedBackdrop.style.fontFamily = e.target.value;
        this.cursorManager.syncMirrorStyles();
        this.cursorManager.renderAll();
      });

      this.dom.fontSizeSelect.addEventListener("change", (e) => {
        this.dom.editorTextarea.style.fontSize = e.target.value;
        if (this.dom.formattedBackdrop) this.dom.formattedBackdrop.style.fontSize = e.target.value;
        this.cursorManager.syncMirrorStyles();
        this.cursorManager.renderAll();
      });

      // Export Menu
      this.dom.btnExportMenu.addEventListener("click", (e) => {
        e.stopPropagation();
        this.dom.btnExportMenu.closest(".dropdown-wrapper").classList.toggle("open");
      });

      document.addEventListener("click", () => {
        document.querySelectorAll(".dropdown-wrapper").forEach((w) => w.classList.remove("open"));
      });

      this.dom.exportDropdown.querySelectorAll(".dropdown-item").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const item = e.target.closest(".dropdown-item");
          const format = item.getAttribute("data-export");
          this.exportDocument(format);
        });
      });

      // Version History Drawer
      this.dom.btnVersionHistory.addEventListener("click", () => this.openVersionHistory());
      this.dom.btnCloseHistory.addEventListener("click", () => this.closeVersionHistory());
      this.dom.btnRestoreVersion.addEventListener("click", () => {
        if (this.previewingVersion !== null) {
          this.ws.send({
            type: "restore_version",
            docId: this.currentDocId,
            targetVersion: this.previewingVersion,
            userId: this.userId,
          });
          this.closeVersionHistory();
        }
      });

      // Modals
      this.dom.btnConfirmRename.addEventListener("click", () => this.confirmRename());
      this.dom.btnConfirmDelete.addEventListener("click", () => this.confirmDelete());
      document.querySelectorAll(".modal-close-btn").forEach((btn) => {
        btn.addEventListener("click", () => this.closeModals());
      });
    }

    insertTextAtCursor(text) {
      const textarea = this.dom.editorTextarea;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const oldVal = textarea.value;

      textarea.value = oldVal.substring(0, start) + text + oldVal.substring(end);
      textarea.selectionStart = textarea.selectionEnd = start + text.length;

      this.handleLocalInput();
    }

    handleLocalInput() {
      const currentText = this.dom.editorTextarea.value;
      const previousText = this.lastEditorText;

      if (currentText === previousText) return;

      // Extract minimal diff operations
      const diffOps = OTClient.diff(previousText, currentText);
      this.lastEditorText = currentText;

      if (diffOps && diffOps.length > 0) {
        diffOps.forEach((op) => {
          this.ot.applyLocalOperation(op);
          this.cursorManager.adjustCursorsForOperation(op);
          this.adjustFormattingForTextOp(op);
        });
      }

      this.renderFormattedBackdrop();
      this.updateLineNumbers();
      this.updateStatistics();
      this.updateUndoRedoUI();
      this.broadcastCursor();
    }

    // -------------------------------------------------------------------------
    // Rich Text Formatting Engine
    // -------------------------------------------------------------------------

    applyFormat(attrName, val) {
      const textarea = this.dom.editorTextarea;
      let start = textarea.selectionStart !== textarea.selectionEnd
        ? textarea.selectionStart
        : this.savedSelStart;
      let end = textarea.selectionStart !== textarea.selectionEnd
        ? textarea.selectionEnd
        : this.savedSelEnd;

      // If no text is selected and user clicked a heading or blockquote, select the current line
      if (start === end && (attrName === "header" || attrName === "blockquote")) {
        const text = textarea.value;
        start = text.lastIndexOf("\n", start - 1) + 1;
        end = text.indexOf("\n", end);
        if (end === -1) end = text.length;
      }

      if (start >= end && attrName !== "clear") {
        this.showToast("Select text to apply formatting");
        return;
      }

      let attributes = {};
      if (attrName === "clear") {
        attributes = { bold: false, italic: false, underline: false, header: 0, blockquote: false, code: false };
      } else {
        // Toggle formatting if already active in selection
        const isAlreadyActive = this.isAttrActiveInRange(start, end, attrName, val);
        attributes[attrName] = isAlreadyActive ? false : val;
      }

      // Capture previous attributes for exact undo
      const prevAttrs = this.getAttrsInRange(start, end);
      const formatOp = OTClient.createFormat(start, end, attributes, this.userId, null, prevAttrs);

      this.ot.applyLocalOperation(formatOp);
      this.applyFormatToLocalStore(start, end, attributes);
      this.renderFormattedBackdrop();
      this.updateUndoRedoUI();
      this.showToast(`Applied ${attrName}`);
    }

    isAttrActiveInRange(start, end, attr, targetVal) {
      for (const iv of this.formattingIntervals) {
        const [s, e, a] = iv;
        if (s <= start && e >= end && a[attr] === targetVal) {
          return true;
        }
      }
      return false;
    }

    getAttrsInRange(start, end) {
      const result = {};
      for (const [s, e, a] of this.formattingIntervals) {
        if (e > start && s < end) {
          Object.assign(result, a);
        }
      }
      return result;
    }

    applyFormatToLocalStore(start, end, attributes) {
      if (end <= start) return;

      const setAttrs = {};
      const removeAttrs = new Set();
      for (const [k, v] of Object.entries(attributes)) {
        if (v !== false && v !== null && v !== 0 && v !== "") {
          setAttrs[k] = v;
        } else {
          removeAttrs.add(k);
        }
      }
      const affected = new Set([...Object.keys(setAttrs), ...removeAttrs]);

      const newIntervals = [];
      for (const [s, e, a] of this.formattingIntervals) {
        if (e <= start || s >= end) {
          newIntervals.push([s, e, Object.assign({}, a)]);
          continue;
        }
        if (s < start) {
          newIntervals.push([s, start, Object.assign({}, a)]);
        }
        if (e > end) {
          newIntervals.push([end, e, Object.assign({}, a)]);
        }
        const midS = Math.max(s, start);
        const midE = Math.min(e, end);
        if (midE > midS) {
          const mid = {};
          for (const [k, v] of Object.entries(a)) {
            if (!affected.has(k)) mid[k] = v;
          }
          if (Object.keys(mid).length > 0) {
            newIntervals.push([midS, midE, mid]);
          }
        }
      }

      if (Object.keys(setAttrs).length > 0) {
        newIntervals.push([start, end, Object.assign({}, setAttrs)]);
      }

      newIntervals.sort((a, b) => a[0] - b[0]);
      this.formattingIntervals = newIntervals;
    }

    adjustFormattingForTextOp(op) {
      if (op.type === "insert") {
        const p = op.pos;
        const len = op.text.length;
        for (const iv of this.formattingIntervals) {
          if (iv[0] >= p) iv[0] += len;
          if (iv[1] >= p) iv[1] += len;
        }
      } else if (op.type === "delete") {
        const start = op.pos;
        const end = op.pos + op.length;
        const len = op.length;
        const newIntervals = [];

        for (const [s, e, a] of this.formattingIntervals) {
          if (e <= start || s >= end) {
            let ns = s;
            let ne = e;
            if (ns >= end) {
              ns -= len;
              ne -= len;
            }
            newIntervals.push([ns, ne, a]);
            continue;
          }
          if (s < start) newIntervals.push([s, start, Object.assign({}, a)]);
          if (e > end) newIntervals.push([end - len, e - len, Object.assign({}, a)]);
        }
        this.formattingIntervals = newIntervals;
      }
    }

    renderFormattedBackdrop() {
      const textarea = this.dom.editorTextarea;
      const text = textarea.value;
      if (!this.dom.formattedBackdrop) return;
      if (!text) {
        this.dom.formattedBackdrop.innerHTML = "";
        return;
      }

      // Image intervals keyed by their start position. Used as a fallback when a
      // stored document has the image formatting but is missing the literal
      // \uFFFC placeholder character in its text (e.g. imported/legacy docs).
      const imageStarts = new Map();
      for (const iv of this.formattingIntervals) {
        const [s, e, a] = iv;
        if (a && a.image && s >= 0 && s < text.length && !imageStarts.has(s)) {
          imageStarts.set(s, iv);
        }
      }

      const chars = [...text];
      let html = "";

      for (let pos = 0; pos < chars.length; pos++) {
        const char = chars[pos];

        if (char === "\uFFFC") {
          const imgInterval = this.formattingIntervals.find(
            ([s, e, a]) => s <= pos && e > pos && a && a.image
          );
          if (imgInterval) {
            html += this.buildImageHtml(imgInterval, pos);
            continue;
          }
        }

        // Fallback: image formatting exists but the text has no \uFFFC anchor.
        // Render the image in place of the character at the interval start so it
        // still appears (and the flow stays roughly aligned).
        const fallbackIv = imageStarts.get(pos);
        if (fallbackIv) {
          html += this.buildImageHtml(fallbackIv, pos);
          continue;
        }

        const escaped = char === "&" ? "&amp;"
          : char === "<" ? "&lt;"
          : char === ">" ? "&gt;"
          : char;

        const attrs = {};
        for (const [s, e, a] of this.formattingIntervals) {
          if (s <= pos && e > pos && !(a && a.image)) {
            Object.assign(attrs, a);
          }
        }

        let chunk = escaped;
        if (attrs.bold)       chunk = `<strong>${chunk}</strong>`;
        if (attrs.italic)     chunk = `<em>${chunk}</em>`;
        if (attrs.underline)  chunk = `<u>${chunk}</u>`;
        if (attrs.code)       chunk = `<code>${chunk}</code>`;

        html += chunk;
      }

      this.dom.formattedBackdrop.innerHTML = html;
      this.dom.formattedBackdrop.scrollTop = textarea.scrollTop;
      this.syncResizeOverlay();
    }

    buildImageHtml(iv, pos) {
      const attrs = iv[2];
      const w = Math.min(attrs.width || 400, 560);
      return `<img class="editor-image" data-char-pos="${pos}" src="/api/images/${attrs.image}" width="${w}" alt="image" onerror="this.outerHTML='<span class=\\'image-placeholder\\'>Image unavailable</span>'">`;
    }
    sendOperationToServer(op, version) {
      this.dom.statSaveStatus.textContent = "Syncing...";

      if (!this.isOnline) {
        this.offlineQueue.push({ op, version });
        this.dom.statSaveStatus.textContent =
          `Offline — ${this.offlineQueue.length} op(s) queued`;
        return;
      }

      const sent = this.ws.send({
        type: "operation",
        docId: this.currentDocId,
        userId: this.userId,
        version: version,
        op: op,
      });

      if (!sent) {
        this.offlineQueue.push({ op, version });
        this.dom.statSaveStatus.textContent =
          `Offline — ${this.offlineQueue.length} op(s) queued`;
      }
    }

    flushOfflineQueue() {
      if (this.offlineQueue.length === 0) return;

      const queue = this.offlineQueue.slice();
      this.offlineQueue = [];

      this.showToast(
        `Reconnected — replaying ${queue.length} offline op(s)`
      );

      for (const { op, version } of queue) {
        this.ws.send({
          type: "operation",
          docId: this.currentDocId,
          userId: this.userId,
          version: version,
          op: op,
        });
      }

      this.dom.statSaveStatus.textContent = "Syncing...";
    }

    applyRemoteOperation(op) {
      const textarea = this.dom.editorTextarea;
      let selStart = textarea.selectionStart;
      let selEnd = textarea.selectionEnd;

      const currentText = this.lastEditorText;
      let newText = currentText;

      if (op.type === "insert") {
        newText = currentText.substring(0, op.pos) + op.text + currentText.substring(op.pos);
        if (selStart >= op.pos) selStart += op.text.length;
        if (selEnd >= op.pos) selEnd += op.text.length;
        this.adjustFormattingForTextOp(op);
      } else if (op.type === "delete") {
        const delEnd = op.pos + op.length;
        newText = currentText.substring(0, op.pos) + currentText.substring(delEnd);
        if (selStart > delEnd) selStart -= op.length;
        else if (selStart > op.pos) selStart = op.pos;
        if (selEnd > delEnd) selEnd -= op.length;
        else if (selEnd > op.pos) selEnd = op.pos;
        this.adjustFormattingForTextOp(op);
      } else if (op.type === "format") {
        this.applyFormatToLocalStore(op.start, op.end, op.attributes);
      }

      this.lastEditorText = newText;
      if (!this.isPreviewing) {
        textarea.value = newText;
        textarea.selectionStart = selStart;
        textarea.selectionEnd = selEnd;
      }

      this.cursorManager.adjustCursorsForOperation(op);
      this.renderFormattedBackdrop();
      this.updateLineNumbers();
      this.updateStatistics();
    }

    handleCursorMove() {
      this.detectSelectedImage();
      this.savedSelStart = this.dom.editorTextarea.selectionStart;
      this.savedSelEnd = this.dom.editorTextarea.selectionEnd;
      clearTimeout(this.cursorDebounceTimer);
      this.cursorDebounceTimer = setTimeout(() => {
        this.broadcastCursor();
        this.updateCursorStats();
      }, 50);
    }

    detectSelectedImage() {
      const textarea = this.dom.editorTextarea;
      const pos = textarea.selectionStart;
      const char = textarea.value[pos];

      if (char === "\uFFFC") {
        const iv = this.formattingIntervals.find(
          ([s, e, a]) => s <= pos && e > pos && a && a.image
        );
        if (iv) {
          this.selectedImagePos = pos;
          this.syncResizeOverlay();
          return;
        }
      }

      if (this.selectedImagePos !== null) {
        this.selectedImagePos = null;
        this.syncResizeOverlay();
      }
    }

    selectImageAt(pos) {
      if (pos === null || pos < 0) return;
      const iv = this.formattingIntervals.find(
        ([s, e, a]) => s <= pos && e > pos && a && a.image
      );
      if (!iv) return;
      this.selectedImagePos = pos;
      const textarea = this.dom.editorTextarea;
      textarea.focus();
      textarea.selectionStart = textarea.selectionEnd = pos + 1;
      this.syncResizeOverlay();
    }

    deleteSelectedImage() {
      const pos = this.selectedImagePos;
      if (pos === null) return;
      const textarea = this.dom.editorTextarea;
      const text = textarea.value;
      if (text[pos] !== "\uFFFC") {
        this.selectedImagePos = null;
        this.syncResizeOverlay();
        return;
      }

      const newText = text.substring(0, pos) + text.substring(pos + 1);
      textarea.value = newText;
      this.handleLocalInput();

      this.formattingIntervals = this.formattingIntervals.filter(
        ([s, e, a]) => !(s <= pos && e > pos && a && a.image)
      );

      this.selectedImagePos = null;
      this.syncResizeOverlay();
      this.renderFormattedBackdrop();
      this.updateLineNumbers();
      this.updateStatistics();
      this.showToast("Image deleted");
    }

    syncResizeOverlay() {
      const overlay = document.getElementById("image-resize-overlay");
      if (!overlay) return;

      if (this.selectedImagePos === null || this.resizeDragState) {
        overlay.style.display = "none";
        return;
      }

      const img = this.dom.formattedBackdrop
        .querySelector(`img[data-char-pos="${this.selectedImagePos}"]`);

      if (!img) {
        overlay.style.display = "none";
        return;
      }

      const rect = img.getBoundingClientRect();
      const scrollY = window.scrollY || 0;
      const scrollX = window.scrollX || 0;

      overlay.style.display = "block";
      overlay.style.left = `${rect.left + scrollX}px`;
      overlay.style.top = `${rect.top + scrollY}px`;
      overlay.style.width = `${rect.width}px`;
      overlay.style.height = `${rect.height}px`;
    }

    initImageResize() {
      const overlay = document.createElement("div");
      overlay.id = "image-resize-overlay";
      overlay.style.display = "none";
      overlay.innerHTML = `
        <div class="resize-handle resize-handle-tl" data-corner="tl"></div>
        <div class="resize-handle resize-handle-tr" data-corner="tr"></div>
        <div class="resize-handle resize-handle-bl" data-corner="bl"></div>
        <div class="resize-handle resize-handle-br" data-corner="br"></div>
      `;
      document.body.appendChild(overlay);

      overlay.addEventListener("mousedown", (e) => {
        const handle = e.target.closest(".resize-handle");
        if (!handle) return;
        e.preventDefault();

        const pos = this.selectedImagePos;
        if (pos === null) return;

        const iv = this.formattingIntervals.find(
          ([s, en, a]) => s <= pos && en > pos && a && a.image
        );
        if (!iv) return;

        const img = this.dom.formattedBackdrop
          .querySelector(`img[data-char-pos="${pos}"]`);
        if (!img) return;

        this.resizeDragState = {
          pos,
          corner: handle.dataset.corner,
          startX: e.clientX,
          startY: e.clientY,
          startWidth: img.getBoundingClientRect().width,
          startHeight: img.getBoundingClientRect().height,
          imgId: iv[2].image,
        };

        overlay.style.pointerEvents = "all";
      });

      window.addEventListener("mousemove", (e) => {
        if (!this.resizeDragState) return;
        const d = this.resizeDragState;

        const dx = e.clientX - d.startX;
        const dy = e.clientY - d.startY;

        let newW = Math.max(50, Math.min(560, d.startWidth + dx));
        let newH = Math.max(30, d.startHeight + dy);

        const ratio = d.startHeight / d.startWidth;
        newH = Math.round(newW * ratio);

        overlay.style.width = `${newW}px`;
        overlay.style.height = `${newH}px`;
      });

      window.addEventListener("mouseup", (e) => {
        if (!this.resizeDragState) return;
        const d = this.resizeDragState;

        const newW = parseInt(overlay.style.width, 10);
        const newH = parseInt(overlay.style.height, 10);

        this.applyFormatToLocalStore(d.pos, d.pos + 1, {
          image: d.imgId,
          width: newW,
          height: newH,
        });

        const prevAttrs = { image: d.imgId, width: d.startWidth, height: d.startHeight };
        const formatOp = OTClient.createFormat(
          d.pos, d.pos + 1,
          { image: d.imgId, width: newW, height: newH },
          this.userId, null, prevAttrs
        );
        this.ot.applyLocalOperation(formatOp);

        this.resizeDragState = null;
        overlay.style.pointerEvents = "none";

        this.renderFormattedBackdrop();
        this.showToast(`Image resized to ${newW}×${newH}px`);
      });

      document.addEventListener("mousedown", (e) => {
        if (
          this.resizeDragState ||
          e.target.closest("#image-resize-overlay") ||
          e.target === this.dom.editorTextarea
        ) return;
        this.selectedImagePos = null;
        overlay.style.display = "none";
      });

      this.dom.editorTextarea.addEventListener("scroll", () => {
        this.syncResizeOverlay();
      });

      // Click an image in the backdrop to select it (shows the resize handles).
      this.dom.formattedBackdrop.addEventListener("click", (e) => {
        const img = e.target.closest(".editor-image");
        if (!img) return;
        const pos = parseInt(img.dataset.charPos, 10);
        if (!Number.isNaN(pos)) this.selectImageAt(pos);
      });
    }

    broadcastCursor() {
      const textarea = this.dom.editorTextarea;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;

      const lines = textarea.value.substring(0, start).split("\n");
      const line = lines.length;
      const col = lines[lines.length - 1].length + 1;

      this.ws.send({
        type: "cursor",
        docId: this.currentDocId,
        userId: this.userId,
        cursor: {
          start: start,
          end: end,
          line: line,
          col: col,
        },
      });
    }

    updateCursorStats() {
      const textarea = this.dom.editorTextarea;
      const start = textarea.selectionStart;
      const lines = textarea.value.substring(0, start).split("\n");
      const line = lines.length;
      const col = lines[lines.length - 1].length + 1;
      this.dom.statCursor.textContent = `Ln ${line}, Col ${col}`;
    }

    executeUndo() {
      const op = this.ot.undo();
      if (op) {
        this.applyUndoRedoOpToDOM(op);
        this.updateUndoRedoUI();
      }
    }

    executeRedo() {
      const op = this.ot.redo();
      if (op) {
        this.applyUndoRedoOpToDOM(op);
        this.updateUndoRedoUI();
      }
    }

    applyUndoRedoOpToDOM(op) {
      const textarea = this.dom.editorTextarea;
      const cur = textarea.value;
      let next = cur;
      let targetCursor = op.pos || 0;

      if (op.type === "insert") {
        next = cur.substring(0, op.pos) + op.text + cur.substring(op.pos);
        targetCursor = op.pos + op.text.length;
        this.adjustFormattingForTextOp(op);
      } else if (op.type === "delete") {
        next = cur.substring(0, op.pos) + cur.substring(op.pos + op.length);
        targetCursor = op.pos;
        this.adjustFormattingForTextOp(op);
      } else if (op.type === "format") {
        this.applyFormatToLocalStore(op.start, op.end, op.attributes);
        targetCursor = op.start;
      }

      this.lastEditorText = next;
      textarea.value = next;
      textarea.selectionStart = textarea.selectionEnd = targetCursor;

      this.renderFormattedBackdrop();
      this.updateLineNumbers();
      this.updateStatistics();
      this.broadcastCursor();
    }

    updateUndoRedoUI() {
      this.dom.btnUndo.disabled = !this.ot.canUndo();
      this.dom.btnRedo.disabled = !this.ot.canRedo();
    }

    // -------------------------------------------------------------------------
    // Statistics & Line Numbers
    // -------------------------------------------------------------------------

    updateLineNumbers() {
      const text = this.dom.editorTextarea.value;
      const lineCount = (text.match(/\n/g) || []).length + 1;

      let gutterHtml = "";
      for (let i = 1; i <= lineCount; i++) {
        gutterHtml += `<div class="line-number">${i}</div>`;
      }
      this.dom.editorGutter.innerHTML = gutterHtml;
    }

    updateStatistics() {
      const text = this.dom.editorTextarea.value;
      const charCount = text.length;
      const words = text.trim() ? text.trim().split(/\s+/).length : 0;

      this.dom.statChars.textContent = `${charCount} character${charCount === 1 ? "" : "s"}`;
      this.dom.statWords.textContent = `${words} word${words === 1 ? "" : "s"}`;
      this.dom.statVersion.innerHTML = `Version: <strong>${this.ot.docVersion}</strong>`;
    }

    // -------------------------------------------------------------------------
    // Document Export (Markdown, Plain Text, JSON)
    // -------------------------------------------------------------------------

    exportDocument(format) {
      const text = this.dom.editorTextarea.value;
      const safeTitle = (this.currentDocTitle || this.currentDocId || "document").replace(/[^a-zA-Z0-9_-]/g, "_");

      if (format === "pdf") {
        const url = `/api/documents/${this.currentDocId}/export?format=pdf`;
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeTitle}.pdf`;
        a.click();
        this.showToast(`Exported as ${safeTitle}.pdf`);
        return;
      }

      if (format === "docx") {
        const url = `/api/documents/${this.currentDocId}/export?format=docx`;
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeTitle}.docx`;
        a.click();
        this.showToast(`Exported as ${safeTitle}.docx`);
        return;
      }

      let content = text;
      let mime = "text/plain;charset=utf-8";
      let ext = "txt";

      if (format === "md" || format === "markdown") {
        content = this.convertToMarkdown(text, this.formattingIntervals);
        mime = "text/markdown;charset=utf-8";
        ext = "md";
      } else if (format === "json") {
        content = JSON.stringify(
          {
            docId: this.currentDocId,
            title: this.currentDocTitle,
            version: this.ot.docVersion,
            content: text,
            formatting: this.formattingIntervals,
            exportedAt: new Date().toISOString(),
          },
          null,
          2
        );
        mime = "application/json;charset=utf-8";
        ext = "json";
      }

      const filename = `${safeTitle}.${ext}`;
      const blob = new Blob([content], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      this.showToast(`Exported as ${filename}`);
    }

    convertToMarkdown(text, intervals) {
      if (!intervals || intervals.length === 0) return text;

      const attrIndex = {};
      for (const [s, e, a] of intervals) {
        for (let i = s; i < e; i++) {
          if (i < text.length) {
            attrIndex[i] = Object.assign({}, attrIndex[i] || {}, a);
          }
        }
      }

      const lines = text.split("\n");
      const out = [];
      let pos = 0;

      for (const line of lines) {
        const lineLen = line.length;
        let header = 0;
        if (lineLen > 0 && attrIndex[pos]) {
          header = attrIndex[pos].header || 0;
        }

        let rendered = "";
        let active = [];

        for (let i = 0; i < lineLen; i++) {
          const attrs = attrIndex[pos + i] || {};
          const newActive = [];
          if (attrs.bold) newActive.push("bold");
          if (attrs.italic) newActive.push("italic");
          if (attrs.underline) newActive.push("underline");
          if (attrs.code) newActive.push("code");

          for (let k = active.length - 1; k >= 0; k--) {
            if (!newActive.includes(active[k])) {
              if (active[k] === "bold") rendered += "**";
              else if (active[k] === "italic") rendered += "*";
              else if (active[k] === "underline") rendered += "</u>";
              else if (active[k] === "code") rendered += "`";
            }
          }

          for (const k of newActive) {
            if (!active.includes(k)) {
              if (k === "bold") rendered += "**";
              else if (k === "italic") rendered += "*";
              else if (k === "underline") rendered += "<u>";
              else if (k === "code") rendered += "`";
            }
          }

          rendered += line[i];
          active = newActive;
        }

        for (let k = active.length - 1; k >= 0; k--) {
          if (active[k] === "bold") rendered += "**";
          else if (active[k] === "italic") rendered += "*";
          else if (active[k] === "underline") rendered += "</u>";
          else if (active[k] === "code") rendered += "`";
        }

        if (header > 0) {
          rendered = "#".repeat(header) + " " + rendered;
        } else if (lineLen > 0 && attrIndex[pos] && attrIndex[pos].blockquote) {
          rendered = "> " + rendered;
        }

        out.push(rendered);
        pos += lineLen + 1;
      }

      return out.join("\n");
    }

    // -------------------------------------------------------------------------
    // Version History Drawer & Time Travel
    // -------------------------------------------------------------------------

    openVersionHistory() {
      this.dom.historyDrawer.classList.add("open");
      this.ws.send({
        type: "get_history",
        docId: this.currentDocId,
      });
    }

    closeVersionHistory() {
      this.dom.historyDrawer.classList.remove("open");
      this.dom.historyPreviewBanner.style.display = "none";
      this.previewingVersion = null;
      this.isPreviewing = false;

      this.dom.editorTextarea.value = this.lastEditorText;
      this.dom.editorTextarea.readOnly = false;
      this.renderFormattedBackdrop();
      this.updateLineNumbers();
    }

    renderVersionHistoryTimeline(history, snapshots) {
      this.dom.historyTimelineList.innerHTML = "";

      if (history.length === 0) {
        this.dom.historyTimelineList.innerHTML = `
          <div style="color: var(--text-muted); font-size: 13px;">No history entries recorded yet.</div>
        `;
        return;
      }

      const reversed = [...history].reverse();
      reversed.forEach((item) => {
        const el = document.createElement("div");
        el.className = "history-item";

        const date = new Date(item.timestamp * 1000);
        const timeStr = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

        el.innerHTML = `
          <div class="history-item-top">
            <span class="history-item-version">Version ${item.version}</span>
            <span class="history-item-time">${timeStr}</span>
          </div>
          <div class="history-item-meta">
            ${(item.type || "edit").toUpperCase()} by <strong>${this.escapeHtml(item.userId || "Collaborator")}</strong>
          </div>
        `;

        el.addEventListener("click", () => {
          document.querySelectorAll(".history-item").forEach((h) => h.classList.remove("selected"));
          el.classList.add("selected");
          this.ws.send({
            type: "get_snapshot",
            docId: this.currentDocId,
            version: item.version,
          });
        });

        this.dom.historyTimelineList.appendChild(el);
      });
    }

    previewSnapshot(version, content, formatting) {
      this.previewingVersion = version;
      this.isPreviewing = true;
      this.dom.historyPreviewBanner.style.display = "flex";
      this.dom.previewVersionNum.textContent = version;

      this.dom.editorTextarea.value = content;
      this.dom.editorTextarea.readOnly = true;
      this.formattingIntervals = formatting || [];
      this.renderFormattedBackdrop();
      this.updateLineNumbers();
      this.showToast(`Previewing version ${version} (Read-Only)`);
    }

    // -------------------------------------------------------------------------
    // Document Import (.docx)
    // -------------------------------------------------------------------------

    initImport() {
      const fileInput = document.getElementById("import-file-input");
      const dropZone  = document.getElementById("import-drop-zone");
      const progress  = document.getElementById("import-progress");

      if (fileInput) {
        fileInput.addEventListener("change", (e) => {
          const file = e.target.files[0];
          if (file) this.handleImportFile(file);
          fileInput.value = "";
        });
      }

      if (dropZone) {
        dropZone.addEventListener("dragover", (e) => {
          e.preventDefault();
          dropZone.classList.add("drag-over");
        });
        dropZone.addEventListener("dragleave", () => {
          dropZone.classList.remove("drag-over");
        });
        dropZone.addEventListener("drop", (e) => {
          e.preventDefault();
          dropZone.classList.remove("drag-over");
          const file = e.dataTransfer.files[0];
          if (file) this.handleImportFile(file);
        });
      }
    }

    async handleImportFile(file) {
      if (!file.name.toLowerCase().endsWith(".docx")) {
        this.showToast("Only .docx files are supported");
        return;
      }

      const dropZone = document.getElementById("import-drop-zone");
      const progress = document.getElementById("import-progress");

      if (dropZone) dropZone.style.display = "none";
      if (progress) progress.style.display = "flex";

      try {
        const formData = new FormData();
        formData.append("file", file);

        const resp = await fetch("/api/documents/import", {
          method: "POST",
          body: formData,
        });

        const data = await resp.json();

        if (resp.ok) {
          this.joinDocument(data.document.docId, data.document.title);
          this.showToast("Document imported successfully");
        } else {
          this.showToast(data.error || "Import failed");
        }
      } catch (err) {
        console.error("Import error:", err);
        this.showToast("Network error during import");
      } finally {
        if (progress) progress.style.display = "none";
        if (dropZone) dropZone.style.display = "";
      }
    }

    // -------------------------------------------------------------------------
    // Image Upload & Insert
    // -------------------------------------------------------------------------

    async uploadImage(file) {
      const formData = new FormData();
      formData.append("file", file);

      const resp = await fetch("/api/images", {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) {
        const data = await resp.json();
        throw new Error(data.error || "Image upload failed");
      }

      return await resp.json();
    }

    insertImageAtCursor(imgId, width, height) {
      const textarea = this.dom.editorTextarea;
      const pos = textarea.selectionStart;

      const before = textarea.value.substring(0, pos);
      const after = textarea.value.substring(pos);
      textarea.value = before + "\uFFFC" + after;
      textarea.selectionStart = textarea.selectionEnd = pos + 1;

      this.handleLocalInput();

      const formatOp = OTClient.createFormat(pos, pos + 1, {
        image: imgId,
        width: Math.min(width, 600),
        height: height,
      }, this.userId, null, {});

      this.ot.applyLocalOperation(formatOp);
      this.applyFormatToLocalStore(pos, pos + 1, {
        image: imgId,
        width: Math.min(width, 600),
        height: height,
      });

      this.renderFormattedBackdrop();
      this.showToast("Image inserted");
    }

    // -------------------------------------------------------------------------
    // Toast Notification Banner
    // -------------------------------------------------------------------------

    showToast(message) {
      const toast = document.createElement("div");
      toast.className = "toast";
      toast.textContent = message;
      this.dom.toastContainer.appendChild(toast);

      setTimeout(() => {
        toast.remove();
      }, 3000);
    }

    updateOfflineBanner(show) {
      let banner = document.getElementById("offline-banner");
      if (show) {
        if (!banner) {
          banner = document.createElement("div");
          banner.id = "offline-banner";
          banner.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 9999;
            background: #b45309;
            color: #fff;
            font-size: 13px;
            font-weight: 600;
            text-align: center;
            padding: 6px 12px;
            letter-spacing: 0.02em;
          `;
          banner.textContent =
            "You are offline — edits are being queued and will sync on reconnect.";
          document.body.prepend(banner);
        }
      } else {
        if (banner) banner.remove();
      }
    }
  }

  window.addEventListener("DOMContentLoaded", () => {
    window.app = new App();
  });
})();
