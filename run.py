#!/usr/bin/env python3
"""
Launcher script for Synapse Collaborative Real-Time Text Editor.

Usage:
    python run.py [--port 8000] [--host 0.0.0.0]
"""

import argparse
import asyncio
import os
import sys

# Ensure backend package is on Python module search path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.server import CollaborativeServer, logger


def main():
    parser = argparse.ArgumentParser(description="Start Synapse Collaborative Real-Time Text Editor Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--frontend", type=str, default="frontend", help="Frontend static assets directory")
    parser.add_argument("--data", type=str, default="data/documents", help="Directory for document snapshots")

    args = parser.parse_args()

    banner = rf"""
========================================================================
   ____                                   
  / ___| _   _ _ __   __ _ _ __  ___  ___ 
  \___ \| | | | '_ \ / _` | '_ \/ __|/ _ \
   ___) | |_| | | | | (_| | |_) \__ \  __/
  |____/ \__, |_| |_|\__,_| .__/|___/\___|
         |___/            |_|             
  Collaborative Real-Time Text Editor (Google Docs Architecture)
========================================================================
  * Architecture:      AVL-balanced Rope Document Representation
  * Concurrency:       Operational Transformation (TP1 Jupiter Model)
  * Real-Time Comms:   Asynchronous WebSockets + Static HTTP Server
  * Web Interface:     http://localhost:{args.port}
========================================================================
    """
    print(banner)

    server = CollaborativeServer(
        host=args.host,
        port=args.port,
        frontend_dir=args.frontend,
        data_dir=args.data,
    )

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped gracefully by user.")


if __name__ == "__main__":
    main()

