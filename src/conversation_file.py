import json
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


def append_user(
    path: str,
    text: str,
    image_name: str | None = None,
    file_attachment: dict | None = None,
) -> None:
    if image_name:
        prefix = f"  [image: {image_name}]\n"
    elif file_attachment:
        prefix = _indent(_file_preview(file_attachment)) + "\n"
    else:
        prefix = ""
    _append(path, f"\nUser:\n{prefix}{_indent(text)}\n")


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
    """Return the full conversation file contents."""
    return Path(path).read_text(encoding="utf-8")


def read_text_for_learn(path: str) -> str:
    """Return conversation text with kb_context blocks stripped.

    The kb_context blocks are useful for auditing but would cause /learn
    to duplicate existing knowledge base content.
    """
    return _strip_kb_context(Path(path).read_text(encoding="utf-8"))


def append_kb_context(path: str, chunks: list[dict]) -> None:
    """Write a kb_context block to the transcript after the User turn.

    Each chunk dict has 'description', 'distance', and 'content'.
    The full content is indented under each header line so the block
    is self-contained and auditable.
    """
    if not chunks:
        return
    lines = ["kb_context:"]
    for chunk in chunks:
        lines.append(f"  {chunk['distance']:.3f} — {chunk['description']}")
        for content_line in chunk["content"].splitlines():
            lines.append(f"    {content_line}")
    _append(path, "\n".join(lines) + "\n")


def parse_kb_contexts(path: str) -> list[list[dict]]:
    """Extract all kb_context blocks from a conversation file.

    Returns a list of chunk lists, one per kb_context block found,
    in file order. Each chunk is a dict with 'description', 'distance',
    and 'content'.
    """
    import re
    text = Path(path).read_text(encoding="utf-8")
    blocks: list[list[dict]] = []
    for m in re.finditer(
        r"^kb_context:\n((?:[ ]{2,}.+\n)*)",
        text,
        re.MULTILINE,
    ):
        block_text = m.group(1)
        chunks: list[dict] = []
        current_desc = None
        current_dist = 0.0
        content_lines: list[str] = []

        for line in block_text.splitlines():
            if line.startswith("  ") and not line.startswith("    "):
                # Header line: save previous chunk
                if current_desc is not None:
                    chunks.append({
                        "description": current_desc,
                        "distance": current_dist,
                        "content": "\n".join(content_lines),
                    })
                # Parse new header
                header = line.strip()
                if " — " in header:
                    dist_str, desc = header.split(" — ", 1)
                    try:
                        current_dist = float(dist_str)
                    except ValueError:
                        current_dist = 0.0
                    current_desc = desc
                else:
                    current_desc = header
                    current_dist = 0.0
                content_lines = []
            elif line.startswith("    "):
                content_lines.append(line[4:])  # strip 4-space indent

        if current_desc is not None:
            chunks.append({
                "description": current_desc,
                "distance": current_dist,
                "content": "\n".join(content_lines),
            })
        blocks.append(chunks)
    return blocks


def save_messages(path: str, messages: list[dict]) -> None:
    """Persist the full messages list as JSON alongside the .txt file.

    Base64 image data from user uploads is stripped before saving — it adds
    significant weight with no recovery value (charts/tables are what matter).
    A stub source {"type": "omitted"} is left in place so the turn structure
    is preserved.
    """
    json_path = Path(path).with_suffix(".json")
    json_path.write_text(json.dumps(_strip_image_data(messages), ensure_ascii=False, indent=2), encoding="utf-8")


def load_messages(path: str) -> list[dict]:
    """Load messages from the JSON sidecar. Returns [] if not found."""
    json_path = Path(path).with_suffix(".json")
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


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

def _strip_image_data(messages: list[dict]) -> list[dict]:
    """Return a copy of messages with base64 image data replaced by a stub."""
    import copy
    result = []
    for msg in messages:
        if msg.get("role") != "user":
            result.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue
        new_content = []
        for block in content:
            if (
                block.get("type") == "image"
                and block.get("source", {}).get("type") == "base64"
            ):
                block = copy.copy(block)
                block["source"] = {"type": "omitted"}
            new_content.append(block)
        new_msg = dict(msg)
        new_msg["content"] = new_content
        result.append(new_msg)
    return result


def _file_preview(attachment: dict) -> str:
    """Build a compact file representation for the .txt transcript."""
    name = attachment["name"]
    path = attachment.get("path", "")
    size = attachment.get("size", 0)

    if attachment.get("is_binary"):
        return f"[file: {name}]\npath: {path}\nsize: {size // 1024} KB (binary)"

    content = attachment.get("content") or ""
    lines = content.splitlines()
    n = len(lines)
    if n <= 200 and len(content) <= 8_000:
        preview = content
    else:
        head = "\n".join(lines[:10])
        tail = "\n".join(lines[-5:])
        preview = f"{head}\n... ({n - 15} lines omitted) ...\n{tail}"
    return f"[file: {name}]\npath: {path}\n{n} lines\n\n{preview}"


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


def _strip_kb_context(text: str) -> str:
    """Remove all kb_context blocks from conversation text."""
    import re
    # Header lines are 2-space indented; content lines are 4-space indented.
    return re.sub(r"^kb_context:\n(?:[ ]{2,}.+\n)*", "", text, flags=re.MULTILINE)
