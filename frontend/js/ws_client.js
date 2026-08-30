/**
 * WebSocket Connection Client with auto-reconnection and latency heartbeat.
 */
class WebSocketClient {
  constructor(endpoint = "/ws") {
    this.endpoint = endpoint;
    this.socket = null;
    this.isConnected = false;
    this.handlers = new Map();
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 15;
    this.reconnectTimer = null;
    this.pingInterval = null;
    this.currentDocId = null;
    this.userCredentials = null;
    this.latency = 0;
  }

  on(type, callback) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, []);
    }
    this.handlers.get(type).push(callback);
  }

  emitLocal(type, data) {
    const list = this.handlers.get(type) || [];
    list.forEach(cb => {
      try {
        cb(data);
      } catch (err) {
        console.error(`Error in handler for ${type}:`, err);
      }
    });
  }

  connect(docId, userCredentials) {
    this.currentDocId = docId;
    this.userCredentials = userCredentials;

    if (this.socket) {
      try {
        this.socket.close();
      } catch (e) {}
    }

    let protocol = "ws:";
    let host = window.location.host;

    if (window.location.protocol === "https:") {
      protocol = "wss:";
    }

    if (!host || host === "" || window.location.protocol === "file:") {
      host = "localhost:8000";
    }

    const wsUrl = `${protocol}//${host}${this.endpoint}`;

    try {
      this.socket = new WebSocket(wsUrl);

      this.socket.onopen = () => {
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.emitLocal("status_change", { status: "connected" });

        // Immediately send join packet
        this.send({
          type: "join",
          docId: this.currentDocId,
          userId: this.userCredentials.userId,
          userName: this.userCredentials.userName,
          color: this.userCredentials.color,
        });

        // Start ping heartbeat
        this.startHeartbeat();
      };

      this.socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          
          if (message.type === "pong") {
            if (message.timestamp) {
              this.latency = Math.max(1, Date.now() - message.timestamp);
              this.emitLocal("latency_update", this.latency);
            }
            return;
          }

          this.emitLocal(message.type, message);
        } catch (err) {
          console.error("Failed to parse WebSocket message:", err, event.data);
        }
      };

      this.socket.onclose = () => {
        this.isConnected = false;
        this.stopHeartbeat();
        this.emitLocal("status_change", { status: "disconnected" });
        this.scheduleReconnect();
      };

      this.socket.onerror = (err) => {
        console.error("WebSocket error:", err);
      };
    } catch (err) {
      console.error("WebSocket connection failure:", err);
      this.scheduleReconnect();
    }
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.pingInterval = setInterval(() => {
      if (this.isConnected) {
        this.send({ type: "ping", timestamp: Date.now() });
      }
    }, 5000);
  }

  stopHeartbeat() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  scheduleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(5000, 1000 * Math.pow(1.5, this.reconnectAttempts));
      this.emitLocal("status_change", { status: "syncing", message: `Reconnecting in ${(delay/1000).toFixed(1)}s...` });
      
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => {
        if (!this.isConnected && this.currentDocId) {
          this.connect(this.currentDocId, this.userCredentials);
        }
      }, delay);
    }
  }

  send(payload) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  disconnect() {
    this.stopHeartbeat();
    clearTimeout(this.reconnectTimer);
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    this.isConnected = false;
  }
}

