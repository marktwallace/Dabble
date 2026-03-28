import re
from pathlib import Path

KNOWLEDGE_DIR = "knowledge"


def slug_from_description(description: str) -> str:
    slug = description.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = slug[:50].rstrip("-")
    return slug or "chunk"


def _unique_slug(base: str) -> str:
    path = Path(KNOWLEDGE_DIR)
    slug = base
    i = 2
    while (path / f"{slug}.txt").exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def list_registry() -> list[dict]:
    """Return [{slug, description}] for all chunk files in KNOWLEDGE_DIR."""
    results = []
    for p in sorted(Path(KNOWLEDGE_DIR).glob("*.txt")):
        try:
            first_line = next(
                (line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()),
                ""
            )
        except Exception:
            continue
        if first_line.lower().startswith("description:"):
            description = first_line[len("description:"):].strip()
        else:
            description = first_line[:100]
        results.append({"slug": p.stem, "description": description})
    return results


def build_registry_block() -> str:
    """Build the <available_knowledge> block for system prompt injection."""
    if not Path(KNOWLEDGE_DIR).exists():
        return ""
    entries = list_registry()
    if not entries:
        return ""
    lines = ["<available_knowledge>"]
    for e in entries:
        lines.append(f"{e['slug']}: {e['description']}")
    lines.append("</available_knowledge>")
    return "\n".join(lines)


def read_chunk(slug: str) -> str:
    """Return the full content of a chunk file."""
    path = Path(KNOWLEDGE_DIR) / f"{slug}.txt"
    if not path.exists():
        return f"Error: no knowledge chunk named '{slug}'."
    return path.read_text(encoding="utf-8")


def write_chunk(description: str, content: str) -> str:
    """Write a chunk as its own file. Returns the slug used."""
    base = slug_from_description(description)
    slug = _unique_slug(base)
    path = Path(KNOWLEDGE_DIR) / f"{slug}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"description: {description}\n\n{content}", encoding="utf-8")
    return slug
