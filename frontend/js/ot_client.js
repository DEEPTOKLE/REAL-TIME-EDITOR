/**
 * Client-Side Operational Transformation (OT) Engine.
 * 
 * Implements:
 * 1. TP1-compliant transformation for Insert, Delete, Format, and NoOp operations.
 * 2. Jupiter/Google Docs Client State Machine (Synchronized, AwaitingAck, AwaitingWithBuffer).
 * 3. Text diffing engine to extract minimal operations from user input.
 * 4. Local Undo/Redo stack with operation inversion for text and formatting.
 */

class OTClient {
  constructor(userId, onApplyRemote, onSendOperation) {
    this.userId = userId;
    this.onApplyRemote = onApplyRemote; // Callback to update UI when remote op arrives
    this.onSendOperation = onSendOperation; // Callback to send packet over WebSocket

    this.docVersion = 0;
    this.state = "SYNCHRONIZED"; // "SYNCHRONIZED", "AWAITING_ACK", "AWAITING_WITH_BUFFER"
    this.outstandingOp = null;
    this.bufferedOp = null;

    // Undo / Redo Stacks
    this.undoStack = [];
    this.redoStack = [];
    this.isApplyingUndoRedo = false;
  }

  setVersion(version) {
    this.docVersion = version;
  }

  /**
   * Resets all client-side OT state. Called when (re)joining a document so
   * that undo/redo history and in-flight operations from a previous document
   * do not leak into the freshly joined one.
   */
  reset() {
    this.docVersion = 0;
    this.state = "SYNCHRONIZED";
    this.outstandingOp = null;
    this.bufferedOp = null;
    this.undoStack = [];
    this.redoStack = [];
    this.isApplyingUndoRedo = false;
  }

  // ---------------------------------------------------------------------------
  // Operation Factories & Helpers
  // ---------------------------------------------------------------------------

  static createInsert(pos, text, userId, opId) {
    return {
      type: "insert",
      pos: pos,
      text: text,
      userId: userId || "",
      opId: opId || Math.random().toString(36).substring(2, 9),
    };
  }

  static createDelete(pos, length, text, userId, opId) {
    return {
      type: "delete",
      pos: pos,
      length: length,
      text: text || "",
      userId: userId || "",
      opId: opId || Math.random().toString(36).substring(2, 9),
    };
  }

  static createFormat(start, end, attributes, userId, opId, prevAttributes = null) {
    return {
      type: "format",
      start: start,
      end: end,
      attributes: Object.assign({}, attributes),
      prevAttributes: prevAttributes ? Object.assign({}, prevAttributes) : {},
      userId: userId || "",
      opId: opId || Math.random().toString(36).substring(2, 9),
    };
  }

  static createNoOp(userId, opId) {
    return {
      type: "noop",
      userId: userId || "",
      opId: opId || Math.random().toString(36).substring(2, 9),
    };
  }

  static isNoOp(op) {
    if (!op || op.type === "noop") return true;
    if (op.type === "insert" && (!op.text || op.text.length === 0)) return true;
    if (op.type === "delete" && op.length <= 0) return true;
    if (op.type === "format" && (op.end <= op.start || !op.attributes || Object.keys(op.attributes).length === 0)) return true;
    return false;
  }

  static invert(op) {
    if (op.type === "insert") {
      return OTClient.createDelete(op.pos, op.text.length, op.text, op.userId);
    } else if (op.type === "delete") {
      return OTClient.createInsert(op.pos, op.text || " ".repeat(op.length), op.userId);
    } else if (op.type === "format") {
      return OTClient.createFormat(
        op.start,
        op.end,
        Object.assign({}, op.prevAttributes || {}),
        op.userId,
        null,
        Object.assign({}, op.attributes || {})
      );
    }
    return OTClient.createNoOp(op.userId);
  }

  // ---------------------------------------------------------------------------
  // Transformation Function T(op1, op2) -> [op1', op2']
  // ---------------------------------------------------------------------------

  static transform(op1, op2, priorityUser = null) {
    if (OTClient.isNoOp(op1)) return [OTClient.createNoOp(op1.userId, op1.opId), op2];
    if (OTClient.isNoOp(op2)) return [op1, OTClient.createNoOp(op2.userId, op2.opId)];

    // 1. Insert vs Insert
    if (op1.type === "insert" && op2.type === "insert") {
      if (op1.pos < op2.pos) {
        const op1_p = OTClient.createInsert(op1.pos, op1.text, op1.userId, op1.opId);
        const op2_p = OTClient.createInsert(op2.pos + op1.text.length, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      } else if (op1.pos > op2.pos) {
        const op1_p = OTClient.createInsert(op1.pos + op2.text.length, op1.text, op1.userId, op1.opId);
        const op2_p = OTClient.createInsert(op2.pos, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      } else {
        let tie = (op1.userId < op2.userId);
        if (op1.userId === op2.userId) tie = (op1.opId < op2.opId);
        if (priorityUser) {
          if (op1.userId === priorityUser) tie = true;
          else if (op2.userId === priorityUser) tie = false;
        }

        if (tie) {
          const op1_p = OTClient.createInsert(op1.pos, op1.text, op1.userId, op1.opId);
          const op2_p = OTClient.createInsert(op2.pos + op1.text.length, op2.text, op2.userId, op2.opId);
          return [op1_p, op2_p];
        } else {
          const op1_p = OTClient.createInsert(op1.pos + op2.text.length, op1.text, op1.userId, op1.opId);
          const op2_p = OTClient.createInsert(op2.pos, op2.text, op2.userId, op2.opId);
          return [op1_p, op2_p];
        }
      }
    }

    // 2. Insert vs Delete
    if (op1.type === "insert" && op2.type === "delete") {
      const insPos = op1.pos;
      const delStart = op2.pos;
      const delEnd = op2.pos + op2.length;

      if (insPos <= delStart) {
        const op1_p = OTClient.createInsert(op1.pos, op1.text, op1.userId, op1.opId);
        const op2_p = OTClient.createDelete(op2.pos + op1.text.length, op2.length, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      } else if (insPos >= delEnd) {
        const op1_p = OTClient.createInsert(op1.pos - op2.length, op1.text, op1.userId, op1.opId);
        const op2_p = OTClient.createDelete(op2.pos, op2.length, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      } else {
        const op1_p = OTClient.createNoOp(op1.userId, op1.opId);
        const op2_p = OTClient.createDelete(op2.pos, op2.length + op1.text.length, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      }
    }

    // 3. Delete vs Insert
    if (op1.type === "delete" && op2.type === "insert") {
      const [op2_p, op1_p] = OTClient.transform(op2, op1, priorityUser);
      return [op1_p, op2_p];
    }

    // 4. Delete vs Delete
    if (op1.type === "delete" && op2.type === "delete") {
      const s1 = op1.pos, e1 = op1.pos + op1.length;
      const s2 = op2.pos, e2 = op2.pos + op2.length;

      if (e1 <= s2) {
        const op1_p = OTClient.createDelete(op1.pos, op1.length, op1.text, op1.userId, op1.opId);
        const op2_p = OTClient.createDelete(op2.pos - op1.length, op2.length, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      } else if (e2 <= s1) {
        const op1_p = OTClient.createDelete(op1.pos - op2.length, op1.length, op1.text, op1.userId, op1.opId);
        const op2_p = OTClient.createDelete(op2.pos, op2.length, op2.text, op2.userId, op2.opId);
        return [op1_p, op2_p];
      }

      const overlapStart = Math.max(s1, s2);
      const overlapEnd = Math.min(e1, e2);
      const overlapLen = Math.max(0, overlapEnd - overlapStart);

      const newLen1 = op1.length - overlapLen;
      let op1_p;
      if (newLen1 <= 0) {
        op1_p = OTClient.createNoOp(op1.userId, op1.opId);
      } else {
        const shift1 = Math.max(0, Math.min(op2.length, s1 - s2));
        op1_p = OTClient.createDelete(s1 - shift1, newLen1, "", op1.userId, op1.opId);
      }

      const newLen2 = op2.length - overlapLen;
      let op2_p;
      if (newLen2 <= 0) {
        op2_p = OTClient.createNoOp(op2.userId, op2.opId);
      } else {
        const shift2 = Math.max(0, Math.min(op1.length, s2 - s1));
        op2_p = OTClient.createDelete(s2 - shift2, newLen2, "", op2.userId, op2.opId);
      }

      return [op1_p, op2_p];
    }

    // 5. Text vs Format
    if ((op1.type === "insert" || op1.type === "delete") && op2.type === "format") {
      const shifted = OTClient._shiftFormatByText(op2, op1);
      return [op1, shifted];
    }

    // 6. Format vs Text
    if (op1.type === "format" && (op2.type === "insert" || op2.type === "delete")) {
      const shifted = OTClient._shiftFormatByText(op1, op2);
      return [shifted, op2];
    }

    // 7. Format vs Format
    if (op1.type === "format" && op2.type === "format") {
      return OTClient._transformFormatFormat(op1, op2);
    }

    return [op1, op2];
  }

  static _shiftFormatByText(fmt, textOp) {
    let s = fmt.start;
    let e = fmt.end;

    if (textOp.type === "insert") {
      const p = textOp.pos;
      const len = textOp.text.length;
      if (s >= p) s += len;
      if (e >= p) e += len;
    } else if (textOp.type === "delete") {
      const p = textOp.pos;
      const len = textOp.length;
      if (s >= p + len) s -= len;
      else if (s > p) s = p;
      if (e >= p + len) e -= len;
      else if (e > p) e = p;
    }

    return OTClient.createFormat(
      Math.max(0, s),
      Math.max(0, e),
      Object.assign({}, fmt.attributes),
      fmt.userId,
      fmt.opId,
      fmt.prevAttributes
    );
  }

  static _transformFormatFormat(op1, op2) {
    const op1_p = OTClient.createFormat(op1.start, op1.end, Object.assign({}, op1.attributes), op1.userId, op1.opId, op1.prevAttributes);
    const op2_p = OTClient.createFormat(op2.start, op2.end, Object.assign({}, op2.attributes), op2.userId, op2.opId, op2.prevAttributes);

    const overlapStart = Math.max(op1.start, op2.start);
    const overlapEnd = Math.min(op1.end, op2.end);

    if (overlapEnd > overlapStart) {
      const winnerIsOp1 = op1.opId <= op2.opId;
      const loser = winnerIsOp1 ? op2_p : op1_p;
      for (const key of Object.keys(op1.attributes)) {
        if (key in op2.attributes) {
          delete loser.attributes[key];
        }
      }
    }

    return [op1_p, op2_p];
  }

  // ---------------------------------------------------------------------------
  // Input Diffing Engine
  // ---------------------------------------------------------------------------

  static diff(oldStr, newStr) {
    if (oldStr === newStr) return null;

    let start = 0;
    while (
      start < oldStr.length &&
      start < newStr.length &&
      oldStr[start] === newStr[start]
    ) {
      start++;
    }

    let oldEnd = oldStr.length;
    let newEnd = newStr.length;
    while (
      oldEnd > start &&
      newEnd > start &&
      oldStr[oldEnd - 1] === newStr[newEnd - 1]
    ) {
      oldEnd--;
      newEnd--;
    }

    const delLen = oldEnd - start;
    const insText = newStr.substring(start, newEnd);

    if (delLen > 0 && insText.length > 0) {
      return [
        OTClient.createDelete(start, delLen, oldStr.substring(start, oldEnd)),
        OTClient.createInsert(start, insText),
      ];
    } else if (delLen > 0) {
      return [OTClient.createDelete(start, delLen, oldStr.substring(start, oldEnd))];
    } else if (insText.length > 0) {
      return [OTClient.createInsert(start, insText)];
    }

    return null;
  }

  // ---------------------------------------------------------------------------
  // Client OT State Machine
  // ---------------------------------------------------------------------------

  applyLocalOperation(op) {
    if (OTClient.isNoOp(op)) return;

    op.userId = this.userId;

    if (!this.isApplyingUndoRedo) {
      this.undoStack.push(op);
      this.redoStack = [];
    }

    if (this.state === "SYNCHRONIZED") {
      this.outstandingOp = op;
      this.state = "AWAITING_ACK";
      this.onSendOperation(op, this.docVersion);
    } else if (this.state === "AWAITING_ACK") {
      this.bufferedOp = op;
      this.state = "AWAITING_WITH_BUFFER";
    } else if (this.state === "AWAITING_WITH_BUFFER") {
      if (Array.isArray(this.bufferedOp)) {
        this.bufferedOp.push(op);
      } else {
        this.bufferedOp = [this.bufferedOp, op];
      }
    }
  }

  handleServerAck(opId, newVersion) {
    this.docVersion = newVersion;

    if (this.state === "AWAITING_ACK") {
      this.outstandingOp = null;
      this.state = "SYNCHRONIZED";
    } else if (this.state === "AWAITING_WITH_BUFFER") {
      let nextOp;
      if (Array.isArray(this.bufferedOp)) {
        nextOp = this.bufferedOp.shift();
        if (this.bufferedOp.length === 1) {
          this.bufferedOp = this.bufferedOp[0];
        } else if (this.bufferedOp.length === 0) {
          this.bufferedOp = null;
        }
      } else {
        nextOp = this.bufferedOp;
        this.bufferedOp = null;
      }

      this.outstandingOp = nextOp;
      this.state = this.bufferedOp ? "AWAITING_WITH_BUFFER" : "AWAITING_ACK";
      this.onSendOperation(nextOp, this.docVersion);
    }
  }

  handleRemoteOperation(remoteOp, newVersion) {
    this.docVersion = newVersion;

    if (OTClient.isNoOp(remoteOp)) return;

    let opToApply = remoteOp;

    if (this.state === "SYNCHRONIZED") {
      opToApply = remoteOp;
    } else if (this.state === "AWAITING_ACK") {
      const [outstandingPrime, remotePrime] = OTClient.transform(this.outstandingOp, remoteOp);
      this.outstandingOp = outstandingPrime;
      opToApply = remotePrime;
    } else if (this.state === "AWAITING_WITH_BUFFER") {
      const [outstandingPrime, remotePrime1] = OTClient.transform(this.outstandingOp, remoteOp);
      this.outstandingOp = outstandingPrime;

      if (Array.isArray(this.bufferedOp)) {
        let currentRemote = remotePrime1;
        const newBuffer = [];
        for (const bOp of this.bufferedOp) {
          const [bPrime, remPrime] = OTClient.transform(bOp, currentRemote);
          newBuffer.push(bPrime);
          currentRemote = remPrime;
        }
        this.bufferedOp = newBuffer;
        opToApply = currentRemote;
      } else if (this.bufferedOp) {
        const [bufferedPrime, remotePrime2] = OTClient.transform(this.bufferedOp, remotePrime1);
        this.bufferedOp = bufferedPrime;
        opToApply = remotePrime2;
      } else {
        opToApply = remotePrime1;
      }
    }

    if (!OTClient.isNoOp(opToApply)) {
      this.onApplyRemote(opToApply);
    }
  }

  // ---------------------------------------------------------------------------
  // Local Undo / Redo Execution
  // ---------------------------------------------------------------------------

  undo() {
    if (this.undoStack.length === 0) return null;
    const op = this.undoStack.pop();
    const inverseOp = OTClient.invert(op);
    this.redoStack.push(op);

    this.isApplyingUndoRedo = true;
    try {
      this.applyLocalOperation(inverseOp);
    } finally {
      this.isApplyingUndoRedo = false;
    }
    return inverseOp;
  }

  redo() {
    if (this.redoStack.length === 0) return null;
    const op = this.redoStack.pop();
    this.undoStack.push(op);

    this.isApplyingUndoRedo = true;
    try {
      this.applyLocalOperation(op);
    } finally {
      this.isApplyingUndoRedo = false;
    }
    return op;
  }

  canUndo() {
    return this.undoStack.length > 0;
  }

  canRedo() {
    return this.redoStack.length > 0;
  }
}
