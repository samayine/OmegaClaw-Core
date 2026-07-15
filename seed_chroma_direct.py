#!/usr/bin/env python3
"""
Direct ChromaDB seeder — bypasses OmegaClaw and the LLM entirely.
Embeds PC knowledge using sentence-transformers and writes straight to ChromaDB on disk.

Use this when:
  - OmegaClaw won't start and you need to seed before it can answer queries
  - You want to reseed faster than the HTTP channel allows (no 1s/chunk round-trip)

Run INSIDE the container:
  docker exec omegaclaw-alis python3 /PeTTa/repos/OmegaClaw-Core/seed_chroma_direct.py

PC knowledge is defined in data/pc_collection.py — edit that file to add or update entries.
Both this script and seed_pc_knowledge.py read from the same source.
"""
import sys, os, datetime, hashlib

CHROMA_PATH = "/PeTTa/repos/OmegaClaw-Core/memory/chroma_db"

# Import PC chunks from data/ (same source as seed_pc_knowledge.py)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.pc_collection import PC_CHUNKS


def main():
    import chromadb
    from sentence_transformers import SentenceTransformer

    print("Loading embedding model (intfloat/e5-large-v2)...")
    model = SentenceTransformer("intfloat/e5-large-v2")

    print(f"Connecting to ChromaDB at {CHROMA_PATH}...")
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    existing = [c.name for c in client.list_collections()]
    print(f"Existing collections: {existing}")

    # OmegaClaw uses 'memories' as the collection name (petta_lib_chromadb default)
    COLL_NAME = "memories"
    try:
        coll = client.get_collection(COLL_NAME)
        print(f"Using existing collection '{COLL_NAME}' ({coll.count()} entries)")
    except Exception:
        coll = client.get_or_create_collection(COLL_NAME)
        print(f"Created new collection '{COLL_NAME}'")

    print(f"\nSeeding {len(PC_CHUNKS)} PC knowledge entries...\n")
    ok = 0
    for label, text in PC_CHUNKS:
        try:
            embedding = model.encode(f"passage: {text}").tolist()
            doc_id = hashlib.md5(text.encode()).hexdigest()
            ts = datetime.datetime.now().isoformat()
            coll.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[{"timestamp": ts, "label": label}],
            )
            print(f"  OK  {label}")
            ok += 1
        except Exception as e:
            print(f"  FAIL {label}: {e}")

    print(f"\nDone: {ok}/{len(PC_CHUNKS)} entries in '{COLL_NAME}'. Total in collection: {coll.count()}")


if __name__ == "__main__":
    main()
