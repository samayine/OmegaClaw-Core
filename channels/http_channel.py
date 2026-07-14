import json
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


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/query":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        message = data.get("message", "")
        patient_id = data.get("patient_id", "")

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

        print(f"[HTTP] Received query (req_id={req_id}): {message[:80]}...")
        event.wait(timeout=HTTP_TIMEOUT)

        with _lock:
            answer = _responses.pop(req_id, "OmegaClaw did not respond in time.")
            _response_events.pop(req_id, None)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"answer": answer}).encode())

    def log_message(self, format, *args):
        pass  # silence default access log


def start_http(port=5050):
    server = HTTPServer(("0.0.0.0", int(port)), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[HTTP] OmegaClaw HTTP channel listening on :{port}")
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
            print(f"[HTTP] Blocked premature send (no data fetched yet): {msg[:80]}")
            return None
        req_id = _active_request_id  # always deliver to the claimed request, not the latest arrived
        if req_id and req_id in _response_events:
            _responses[req_id] = msg
            _response_events[req_id].set()
            _active_request_id = None
            print(f"[HTTP] Response sent for req_id={req_id}")
            return "sent"
