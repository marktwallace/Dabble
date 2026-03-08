from datetime import datetime
from pathlib import Path


def new_path(conversations_dir: str) -> str:
    """Return a new timestamp-based conversation file path (file not created yet)."""
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M")
    return str(Path(conversations_dir) / f"{ts}.txt")


def write_title(path: str, title: str) -> None:
    """Create the file and write the title as the first line."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(title + "\n")


def append_user(path: str, text: str) -> None:
    _append(path, f"\nUser:\n{_indent(text)}\n")


def append_assistant_turn(
    path: str,
    assistant_content: list[dict],
    tool_results: list[dict],
) -> None:
    """Write one complete assistant turn to the file.

    assistant_content: model_dump'd content blocks from the assistant message.
    tool_results: the tool_result blocks from the following user message (may be empty).
    """
    id_to_result = {
        r["tool_use_id"]: r["content"]
        for r in tool_results
        if r.get("type") == "tool_result"
    }

    lines = ["\nAssistant:"]

    for block in assistant_content:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "").strip()
            if text:
                lines.append(_indent(text))
        elif btype == "tool_use":
            lines.append(f"\ntool_use: {block['name']}")
            for k, v in block.get("input", {}).items():
                lines.append(_kv(k, v))
            result = id_to_result.get(block["id"], "")
            lines.append(f"\ntool_result: {block['name']}")
            if result:
                lines.append(_indent(result))

    lines.append("")
    _append(path, "\n".join(lines) + "\n")


def get_title(path: str) -> str:
    """Return the first line of the file (the conversation title)."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return ""


def read_text(path: str) -> str:
    """Return the full conversation file contents (used by /learn)."""
    return Path(path).read_text(encoding="utf-8")


def list_conversations(conversations_dir: str) -> list[dict]:
    """Return all conversations sorted newest first.

    Each entry: {"path": str, "title": str, "filename": str}
    Skips example.txt.
    """
    paths = sorted(Path(conversations_dir).glob("*.txt"), reverse=True)
    return [
        {"path": str(p), "title": get_title(str(p)), "filename": p.name}
        for p in paths
        if p.name != "example.txt"
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _append(path: str, text: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _kv(key: str, value) -> str:
    """Format a key-value pair, indenting multiline values."""
    text = str(value).strip()
    lines = text.splitlines()
    if len(lines) <= 1:
        return f"  {key}: {text}"
    first = lines[0]
    rest = "\n".join("    " + ln for ln in lines[1:])
    return f"  {key}: {first}\n{rest}"
