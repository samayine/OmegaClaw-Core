"""Unit tests for the loopback HTTP backend's request validation.

Bearer authentication is intentionally tested at the nginx ingress boundary:
the agent process must not hold the bearer token. These tests keep the Python
backend strict about payloads even when it is reached from that proxy.
"""
import importlib.util
import io
import os


_CHANNEL_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "channels", "http_channel.py")
)


def _load_channel():
    spec = importlib.util.spec_from_file_location("http_channel_under_test", _CHANNEL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Request:
    def __init__(self, body, headers):
        self.rfile = io.BytesIO(body)
        self.headers = headers


def test_rejects_missing_or_wrong_content_type():
    channel = _load_channel()
    payload, status, _ = channel._read_json_body(_Request(b'{}', {"Content-Length": "2"}))
    assert payload is None
    assert status == 415


def test_rejects_malformed_and_oversized_payloads():
    channel = _load_channel()
    headers = {"Content-Type": "application/json", "Content-Length": "3"}
    payload, status, _ = channel._read_json_body(_Request(b"{x}", headers))
    assert payload is None
    assert status == 400

    headers["Content-Length"] = str(channel.HTTP_MAX_BODY_BYTES + 1)
    payload, status, _ = channel._read_json_body(_Request(b"", headers))
    assert payload is None
    assert status == 413


def test_accepts_bounded_string_query_only():
    channel = _load_channel()
    body = b'{"message":"summary","patient_id":"p-1"}'
    headers = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))}
    payload, status, error = channel._read_json_body(_Request(body, headers))
    assert (payload, status, error) == (("summary", "p-1"), None, None)

    body = b'{"message": ["not a string"]}'
    headers["Content-Length"] = str(len(body))
    payload, status, _ = channel._read_json_body(_Request(body, headers))
    assert payload is None
    assert status == 400


def test_backend_binds_to_loopback_by_default(monkeypatch):
    channel = _load_channel()
    captured = {}

    class _Server:
        def __init__(self, address, _handler):
            captured["address"] = address

        def serve_forever(self):
            return None

    monkeypatch.setattr(channel, "ThreadingHTTPServer", _Server)
    channel.start_http(5051)
    assert captured["address"] == ("127.0.0.1", 5051)
