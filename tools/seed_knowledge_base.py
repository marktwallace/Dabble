"""Load knowledge/ directory into ChromaDB without clearing existing data.

Run this once when setting up a new domain overlay, or to add new .txt files
to an existing knowledge base without rebuilding from scratch.

Usage:
    python -m tools.seed_knowledge_base
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge_base import add_chunk

KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "knowledge")
KB_PATH = os.environ.get("KB_PATH")
CHUNK_SEPARATOR = "\n---\n"


def main():
    if not KB_PATH:
        print("KB_PATH not set in settings.env")
        sys.exit(1)

    knowledge_dir = Path(KNOWLEDGE_DIR)
    if not knowledge_dir.exists():
        print(f"Knowledge directory not found: {knowledge_dir}")
        sys.exit(1)

    files = sorted(knowledge_dir.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {knowledge_dir}")
        return

    total = 0
    for filepath in files:
        count = 0
        for chunk in filepath.read_text(encoding="utf-8").split(CHUNK_SEPARATOR):
            chunk = chunk.strip()
            if chunk:
                add_chunk(chunk, {"source_file": filepath.name}, KB_PATH)
                count += 1
        print(f"  {filepath.name}: {count} chunks")
        total += count

    print(f"\nAdded {total} chunks to {KB_PATH}")


if __name__ == "__main__":
    main()
