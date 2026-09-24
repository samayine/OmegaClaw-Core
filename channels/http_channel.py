import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

_lock = threading.Lock()
_last_message = ""
_last_request_id = None   # latest arrived request (may change while OmegaClaw is processing)
_active_request_id = None # request OmegaClaw has "claimed" — send_message always delivers to this one
_request_counter = 0
_response_events = {}
_responses = {}
_send_allowed = False  # True only after first empty getLastMessage (data-fetch iteration done)

HTTP_TIMEOUT = 120  # seconds to wait for OmegaClaw to respond


def _positive_int_env(name, default, minimum=1, maximum=None):
    """Read a bounded positive integer without making startup fragile."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    if value < minimum or (maximum is not None and value > maximum):
        return default
    return value


# Keep these bounded even if an operator sets an incorrect environment value.
HTTP_MAX_BODY_BYTES = _positive_int_env("HTTP_MAX_BODY_BYTES", 16 * 1024, maximum=1024 * 1024)
HTTP_MAX_MESSAGE_CHARS = _positive_int_env("HTTP_MAX_MESSAGE_CHARS", 12 * 1024, maximum=1024 * 1024)


def _read_json_body(handler):
    """Return a validated query payload, or ``(None, status, message)``.

    Authentication and rate limiting are deliberately enforced by nginx, before
    traffic reaches this process.  This process runs as the agent user, so it
    must never receive the ingress bearer token in its environment.
    """
    content_type = handler.headers.get("Content-Type", "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return None, 415, "Content-Type must be application/json"

    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        return None, 411, "Content-Length is required"
    if length < 0:
        return None, 400, "Invalid Content-Length"
    if length > HTTP_MAX_BODY_BYTES:
        return None, 413, "Request body is too large"

    try:
        body = handler.rfile.read(length)
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, 400, "Request body must be valid JSON"

    if not isinstance(data, dict):
        return None, 400, "Request body must be a JSON object"
    message = data.get("message", "")
    patient_id = data.get("patient_id", "")
    if not isinstance(message, str) or not isinstance(patient_id, str):
        return None, 400, "message and patient_id must be strings"
    if len(message) > HTTP_MAX_MESSAGE_CHARS or len(patient_id) > 256:
        return None, 413, "Request fields are too large"
    return (message, patient_id), None, None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        # Bound slow clients so a partially sent request cannot block the channel.
        self.connection.settimeout(10)

    def _send_json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        if self.path != "/query":
            self._send_json(404, {"error": "not_found"})
            return

        payload, status, error = _read_json_body(self)
        if error:
            self._send_json(status, {"error": error})
            return
        message, patient_id = payload

        if patient_id:
            message = f"[patient_id:{patient_id}] {message}"

        global _request_counter, _last_message, _last_request_id
        with _lock:
            _request_counter += 1
            req_id = _request_counter
            _last_message = message
            _last_request_id = req_id
            event = threading.Event()
            _response_events[req_id] = event

        # Do not put prompts, patient IDs, or PHI in process logs.
        print(f"[HTTP] Received authenticated query (req_id={req_id}, chars={len(message)}, patient_context={bool(patient_id)})")
        event.wait(timeout=HTTP_TIMEOUT)

        with _lock:
            answer = _responses.pop(req_id, "OmegaClaw did not respond in time.")
            _response_events.pop(req_id, None)

        self._send_json(200, {"answer": answer})

    def log_message(self, format, *args):
        pass  # silence default access log


def start_http(port=5050, host=None):
    """Start the loopback-only backend used by the authenticated nginx proxy."""
    bind_host = host or os.environ.get("HTTP_BIND_HOST", "127.0.0.1")
    # The channel's request/response state is intentionally single-flight.
    # Do not make this threaded until it has a FIFO queue and per-request routing.
    server = HTTPServer((bind_host, int(port)), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[HTTP] OmegaClaw HTTP backend listening on {bind_host}:{port}")
    return t


def getLastMessage():
    global _last_message, _send_allowed, _active_request_id
    with _lock:
        msg = _last_message
        _last_message = ""
        if msg:
            # OmegaClaw is claiming this request — lock in the req_id for delivery
            _active_request_id = _last_request_id
            _send_allowed = False  # block send until data is fetched
        else:
            _send_allowed = True   # subsequent iteration — send is allowed
        return msg


def set_send_allowed():
    """Called by data-fetch skills (get_patient, get_longitudinal) to unblock send in the same iteration."""
    global _send_allowed
    with _lock:
        _send_allowed = True


def send_message(msg):
    global _active_request_id, _send_allowed
    with _lock:
        if not _send_allowed:
            print(f"[HTTP] Blocked premature send (no data fetched yet, chars={len(str(msg))})")
            return None
        req_id = _active_request_id  # always deliver to the claimed request, not the latest arrived
        if req_id and req_id in _response_events:
            _responses[req_id] = msg
            _response_events[req_id].set()
            _active_request_id = None
            print(f"[HTTP] Response sent for req_id={req_id}")
            return "sent"
