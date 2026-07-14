#!/usr/bin/env python3
"""
Transparent LLM proxy: listens on localhost:11434, rewrites the model name
in the request body, and forwards to LLM_SERVER_LOCAL_URL.

All headers (including Authorization) are passed through unchanged,
so OmegaClaw's Ollama-local provider works without any code modifications.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

REMOTE = os.environ.get("LLM_SERVER_LOCAL_URL", "").rstrip("/")
MODEL  = os.environ.get("OLLAMA_MODEL", "gemma4")
PORT   = 11434


class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        try:
            body = json.loads(raw)
            original_model = body.get("model", "?")
            body["model"] = MODEL
            data = json.dumps(body).encode()
            print(f"[llm_proxy] {self.path}  model: {original_model} -> {MODEL}", flush=True)
        except Exception:
            data = raw

        fwd_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length", "transfer-encoding")
        }
        fwd_headers["Content-Length"] = str(len(data))

        req = urllib.request.Request(
            f"{REMOTE}{self.path}",
            data=data,
            headers=fwd_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                while True:
                    chunk = r.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    if not REMOTE:
        print("[llm_proxy] ERROR: LLM_SERVER_LOCAL_URL is not set", flush=True)
        sys.exit(1)
    print(f"[llm_proxy] 0.0.0.0:{PORT} -> {REMOTE}  model rewrite -> {MODEL}", flush=True)
    HTTPServer(("0.0.0.0", PORT), ProxyHandler).serve_forever()
