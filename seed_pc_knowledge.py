"""
Seed PC knowledge into OmegaClaw's ChromaDB via the HTTP channel.
Run AFTER OmegaClaw is up and healthy:

  python3 seed_pc_knowledge.py

To seed from a custom JSON file (list of dicts with 'pc_group' and 'raw_text'):
  python3 seed_pc_knowledge.py path/to/knowledge.json

PC knowledge lives in data/pc_collection.py — edit that file to add or update entries.
"""
import urllib.request, urllib.error, json, time, sys, os

OMEGACLAW_URL = os.environ.get("OMEGACLAW_URL", "http://localhost:5051")
TIMEOUT = 120

# Import PC chunks from data/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.pc_collection import PC_CHUNKS


def seed():
    print(f"Seeding {len(PC_CHUNKS)} PC knowledge entries to {OMEGACLAW_URL}...")
    for i, (label, text) in enumerate(PC_CHUNKS):
        msg = f"remember {text}"
        print(f"[{i+1}/{len(PC_CHUNKS)}] Seeding {label}...", end=" ", flush=True)
        try:
            body = json.dumps({"message": msg, "patient_id": ""}).encode()
            req = urllib.request.Request(
                f"{OMEGACLAW_URL}/query",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
            print(f"OK — {data.get('answer', '')[:60]}")
        except Exception as e:
            print(f"FAILED: {e}")
        time.sleep(1)
    print(f"\nSeeding complete. {len(PC_CHUNKS)} entries in ChromaDB.")


def seed_from_json(json_path: str):
    """Seed from a JSON file. Expects list of dicts with 'pc_group' and 'raw_text'."""
    with open(json_path) as f:
        entries = json.load(f)
    print(f"Seeding {len(entries)} entries from {json_path} to {OMEGACLAW_URL}...")
    tuples = []
    for e in entries:
        label = e.get("pc_group") or e.get("label") or "PC"
        risk_window = e.get("risk_window", "")
        if risk_window and risk_window != "unspecified":
            label = f"{label}_{risk_window}"
        text = e.get("raw_text") or e.get("text") or str(e)
        tuples.append((label, text))
    for i, (label, text) in enumerate(tuples):
        msg = f"remember {text}"
        print(f"[{i+1}/{len(tuples)}] Seeding {label}...", end=" ", flush=True)
        try:
            body = json.dumps({"message": msg, "patient_id": ""}).encode()
            req = urllib.request.Request(
                f"{OMEGACLAW_URL}/query",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
            print(f"OK — {data.get('answer', '')[:60]}")
        except Exception as e:
            print(f"FAILED: {e}")
        time.sleep(1)
    print(f"\nSeeding complete.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        seed_from_json(sys.argv[1])
    else:
        seed()
