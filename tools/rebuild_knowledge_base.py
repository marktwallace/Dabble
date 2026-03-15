"""Clear ChromaDB and reload all chunks from knowledge/ directory.

Use this when you need to re-embed everything (e.g. after changing the
embedding model) or to remove chunks from deleted knowledge files.

Usage:
    python -m tools.rebuild_knowledge_base
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge_base import rebuild_from_directory

KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "knowledge")
KB_PATH = os.environ.get("KB_PATH")


def main():
    if not KB_PATH:
        print("KB_PATH not set in settings.env")
        sys.exit(1)

    knowledge_dir = Path(KNOWLEDGE_DIR)
    if not knowledge_dir.exists():
        print(f"Knowledge directory not found: {knowledge_dir}")
        sys.exit(1)

    print(f"Rebuilding knowledge base at {KB_PATH} from {knowledge_dir} ...")
    count = rebuild_from_directory(str(knowledge_dir), KB_PATH)
    print(f"Done. {count} chunks loaded.")


if __name__ == "__main__":
    main()
