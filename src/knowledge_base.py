import re
from pathlib import Path


def slug_from_description(description: str) -> str:
    slug = description.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = slug[:50].rstrip("-")
    return slug or "chunk"


def _unique_slug(base: str, knowledge_dir: str) -> str:
    path = Path(knowledge_dir)
    slug = base
    i = 2
    while (path / f"{slug}.txt").exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def list_registry(knowledge_dir: str) -> list[dict]:
    """Return [{slug, description}] for all chunk files in knowledge_dir."""
    results = []
    for p in sorted(Path(knowledge_dir).glob("*.txt")):
        try:
            first_line = next(
                (l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()),
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


def build_registry_block(knowledge_dir: str) -> str:
    """Build the <available_knowledge> block for system prompt injection."""
    if not knowledge_dir or not Path(knowledge_dir).exists():
        return ""
    entries = list_registry(knowledge_dir)
    if not entries:
        return ""
    lines = ["<available_knowledge>"]
    for e in entries:
        lines.append(f"{e['slug']}: {e['description']}")
    lines.append("</available_knowledge>")
    return "\n".join(lines)


def read_chunk(slug: str, knowledge_dir: str) -> str:
    """Return the full content of a chunk file."""
    path = Path(knowledge_dir) / f"{slug}.txt"
    if not path.exists():
        return f"Error: no knowledge chunk named '{slug}'."
    return path.read_text(encoding="utf-8")


def write_chunk(description: str, content: str, knowledge_dir: str) -> str:
    """Write a chunk as its own file. Returns the slug used."""
    base = slug_from_description(description)
    slug = _unique_slug(base, knowledge_dir)
    path = Path(knowledge_dir) / f"{slug}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"description: {description}\n\n{content}", encoding="utf-8")
    return slug
