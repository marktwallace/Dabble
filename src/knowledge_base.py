import hashlib
import os
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

COLLECTION_NAME = "list_pet_kb"
CHUNK_SEPARATOR = "\n---\n"
DESCRIPTION_PREFIX = "description: "
DISTANCE_THRESHOLD = 1.0  # L2 distance; ~cosine similarity > 0.5 for normalised embeddings


def _collection(db_path: str):
    client = chromadb.PersistentClient(path=db_path)
    ef = OpenAIEmbeddingFunction(
        api_key=os.environ["OPENAI_API_KEY"],
        model_name="text-embedding-3-small",
    )
    return client.get_or_create_collection(COLLECTION_NAME, embedding_function=ef)


def search(query: str, db_path: str, n_results: int = 5) -> list[dict]:
    """Return up to n_results chunks relevant to query.

    Each result has 'description' (what was embedded) and 'content' (full chunk text).
    Returns [] if the knowledge base is empty.
    """
    col = _collection(db_path)
    if col.count() == 0:
        return []
    results = col.query(
        query_texts=[query],
        n_results=min(n_results, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    return [
        {
            "id": chunk_id,
            "description": doc,
            "content": meta.get("full_text", doc),
            "source": meta.get("source_file", "unknown"),
        }
        for chunk_id, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
        if dist < DISTANCE_THRESHOLD
    ]


def add_chunk(text: str, metadata: dict, db_path: str):
    """Add a single chunk to ChromaDB.

    The first line of the chunk text should start with 'description: ' — that
    line is what gets embedded and matched at retrieval time. The full text is
    stored in metadata and returned to Claude when the chunk is retrieved.

    Uses a content hash as the ID, so rebuilding from the same files is idempotent.
    """
    lines = text.strip().splitlines()
    if lines and lines[0].lower().startswith(DESCRIPTION_PREFIX):
        description = lines[0][len(DESCRIPTION_PREFIX):].strip()
    else:
        description = text[:200]

    chunk_id = hashlib.md5(text.encode()).hexdigest()
    _collection(db_path).add(
        documents=[description],
        metadatas=[{**metadata, "full_text": text}],
        ids=[chunk_id],
    )


def rebuild_from_directory(knowledge_dir: str, db_path: str) -> int:
    """Clear ChromaDB and reload all chunks from knowledge_dir.

    Each .txt file in the directory may contain multiple chunks separated by
    a line containing only '---'. Returns the number of chunks loaded.
    """
    client = chromadb.PersistentClient(path=db_path)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    count = 0
    for filepath in sorted(Path(knowledge_dir).glob("*.txt")):
        source = filepath.name
        for chunk in filepath.read_text(encoding="utf-8").split(CHUNK_SEPARATOR):
            chunk = chunk.strip()
            if chunk:
                add_chunk(chunk, {"source_file": source}, db_path)
                count += 1
    return count
