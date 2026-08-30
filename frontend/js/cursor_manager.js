/**
 * Multi-User Remote Cursor & Selection Overlay Manager.
 * 
 * Accurately measures text coordinates using an invisible mirror div
 * and renders smooth colored carets with author name tags and selection highlights.
 */

class CursorManager {
  constructor(textareaElement, overlayContainer) {
    this.textarea = textareaElement;
    this.overlay = overlayContainer;
    this.users = new Map(); // userId -> { userName, color, cursor: {start, end} }
    this.mirrorDiv = null;

    this.initMirrorDiv();
    this.bindEvents();
  }

  initMirrorDiv() {
    this.mirrorDiv = document.createElement("div");
    this.mirrorDiv.className = "textarea-mirror";
    this.mirrorDiv.style.cssText = `
      position: absolute;
      top: -9999px;
      left: -9999px;
      visibility: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      pointer-events: none;
      overflow: hidden;
    `;
    document.body.appendChild(this.mirrorDiv);
  }

  syncMirrorStyles() {
    if (!this.textarea || !this.mirrorDiv) return;
    const computed = window.getComputedStyle(this.textarea);
    const propertiesToCopy = [
      "fontFamily",
      "fontSize",
      "fontWeight",
      "fontStyle",
      "letterSpacing",
      "lineHeight",
      "textTransform",
      "wordSpacing",
      "textIndent",
      "paddingTop",
      "paddingRight",
      "paddingBottom",
      "paddingLeft",
      "borderLeftWidth",
      "borderTopWidth",
      "boxSizing",
      "tabSize",
    ];

    propertiesToCopy.forEach((prop) => {
      this.mirrorDiv.style[prop] = computed[prop];
    });

    this.mirrorDiv.style.width = `${this.textarea.clientWidth}px`;
  }

  bindEvents() {
    window.addEventListener("resize", () => {
      this.syncMirrorStyles();
      this.renderAll();
    });

    this.textarea.addEventListener("scroll", () => {
      this.renderAll();
    });
  }

  setUsers(userList) {
    this.users.clear();
    userList.forEach((user) => {
      this.users.set(user.userId, {
        userName: user.userName || "Collaborator",
        color: user.color || "#1a73e8",
        cursor: user.cursor || { start: 0, end: 0 },
      });
    });
    this.renderAll();
  }

  updateUser(userId, userData) {
    const existing = this.users.get(userId) || {};
    this.users.set(userId, {
      ...existing,
      ...userData,
    });
    this.renderAll();
  }

  updateUserCursor(userId, cursorData) {
    const user = this.users.get(userId);
    if (user) {
      user.cursor = cursorData;
      this.renderAll();
    }
  }

  removeUser(userId) {
    this.users.delete(userId);
    this.renderAll();
  }

  // Adjust peer cursor indices when text changes
  adjustCursorsForOperation(op) {
    const isInsert = op.type === "insert";
    const pos = op.pos;
    const len = isInsert ? op.text.length : -op.length;

    this.users.forEach((user) => {
      if (!user.cursor) return;
      let { start, end } = user.cursor;

      if (isInsert) {
        if (start >= pos) start += len;
        if (end >= pos) end += len;
      } else {
        const delEnd = pos + op.length;
        if (start > delEnd) start += len;
        else if (start > pos) start = pos;

        if (end > delEnd) end += len;
        else if (end > pos) end = pos;
      }

      user.cursor.start = Math.max(0, start);
      user.cursor.end = Math.max(0, end);
    });

    this.renderAll();
  }

  getCoordinatesForIndex(charIndex) {
    this.syncMirrorStyles();

    const text = this.textarea.value;
    const clampedIndex = Math.max(0, Math.min(charIndex, text.length));

    const textBefore = text.substring(0, clampedIndex);
    const textAfter = text.substring(clampedIndex);

    this.mirrorDiv.textContent = textBefore;

    const markerSpan = document.createElement("span");
    markerSpan.textContent = textAfter.length > 0 ? textAfter[0] : "\u200b"; // zero-width space if end of document
    this.mirrorDiv.appendChild(markerSpan);

    const spanRect = markerSpan.getBoundingClientRect();
    const mirrorRect = this.mirrorDiv.getBoundingClientRect();

    const computed = window.getComputedStyle(this.textarea);
    const paddingLeft = parseFloat(computed.paddingLeft) || 0;
    const paddingTop = parseFloat(computed.paddingTop) || 0;

    const left = spanRect.left - mirrorRect.left + paddingLeft;
    const top = spanRect.top - mirrorRect.top + paddingTop - this.textarea.scrollTop;
    const height = spanRect.height || 22;

    return { left, top, height };
  }

  renderAll() {
    if (!this.overlay) return;
    this.overlay.innerHTML = "";

    this.users.forEach((user, userId) => {
      if (!user.cursor) return;

      const { start, end } = user.cursor;
      const hasSelection = typeof end === "number" && start !== end;
      const selStart = Math.min(start, end);
      const selEnd = Math.max(start, end);

      const color = user.color || "#1a73e8";

      // 1. Render Selection Range Highlight (if any)
      if (hasSelection) {
        const startCoord = this.getCoordinatesForIndex(selStart);
        const endCoord = this.getCoordinatesForIndex(selEnd);

        const selBox = document.createElement("div");
        selBox.className = "remote-selection-box";
        selBox.style.setProperty("--user-color-alpha", this._hexToRgba(color, 0.25));

        if (startCoord.top === endCoord.top) {
          // Single line selection
          selBox.style.left = `${startCoord.left}px`;
          selBox.style.top = `${startCoord.top}px`;
          selBox.style.width = `${Math.max(4, endCoord.left - startCoord.left)}px`;
          selBox.style.height = `${startCoord.height}px`;
          this.overlay.appendChild(selBox);
        } else {
          // Multi-line selection box
          selBox.style.left = `${startCoord.left}px`;
          selBox.style.top = `${startCoord.top}px`;
          selBox.style.width = `${this.textarea.clientWidth - startCoord.left - 20}px`;
          selBox.style.height = `${endCoord.top - startCoord.top + endCoord.height}px`;
          this.overlay.appendChild(selBox);
        }
      }

      // 2. Render Caret Flag at cursor end
      const caretIndex = typeof end === "number" ? end : start;
      const coord = this.getCoordinatesForIndex(caretIndex);

      if (coord.top >= -20 && coord.top <= this.textarea.clientHeight + 20) {
        const cursorEl = document.createElement("div");
        cursorEl.className = "remote-cursor";
        cursorEl.style.setProperty("--user-color", color);
        cursorEl.style.left = `${coord.left}px`;
        cursorEl.style.top = `${coord.top}px`;
        cursorEl.style.height = `${coord.height}px`;

        const flagEl = document.createElement("div");
        flagEl.className = "remote-cursor-flag";
        flagEl.style.setProperty("--user-color", color);
        flagEl.textContent = user.userName || "User";

        cursorEl.appendChild(flagEl);
        this.overlay.appendChild(cursorEl);
      }
    });
  }

  _hexToRgba(hex, alpha) {
    let c = hex.replace("#", "");
    if (c.length === 3) {
      c = c[0] + c[0] + c[1] + c[1] + c[2] + c[2];
    }
    const num = parseInt(c, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
  }
}

