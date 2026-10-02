"""Prompt files that include other prompt files.

A line consisting only of "@<path>", where the path ends in .md or .txt, is replaced
by that file's contents, expanded the same way. This is the import syntax of Claude
Code's CLAUDE.md. Paths are relative to the prompt directory and may not leave it.

Used for the system prompt and for documents read with the read_document tool, so a
prompt can be written as small files and loaded as larger units composed of them.
"""

import re
from pathlib import Path

MAX_DEPTH = 5
_INCLUDE = re.compile(r"^\s*@(\S+\.(?:md|txt))\s*$")


class PromptFileError(Exception):
    pass


def resolve(prompts_dir: str, rel: str) -> Path:
    """The file at rel under prompts_dir. Refuses paths outside it and missing files."""
    root = Path(prompts_dir).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise PromptFileError(f"{rel}: outside the prompt directory")
    if not path.is_file():
        raise PromptFileError(f"{rel}: no such file in the prompt directory")
    return path


def read(prompts_dir: str, rel: str) -> str:
    """The file at rel under prompts_dir, with its includes expanded."""
    path = resolve(prompts_dir, rel)
    return expand(path.read_text(encoding="utf-8"), prompts_dir, (path,))


def expand(text: str, prompts_dir: str, _stack: tuple = ()) -> str:
    """Replace each include line with the included file, expanded. Text without
    include lines is returned unchanged."""
    out = []
    for line in text.splitlines(keepends=True):
        m = _INCLUDE.match(line)
        if not m:
            out.append(line)
            continue
        path = resolve(prompts_dir, m.group(1))
        if path in _stack:
            raise PromptFileError(f"{m.group(1)}: includes itself (cycle)")
        if len(_stack) > MAX_DEPTH:
            raise PromptFileError(f"{m.group(1)}: includes nested deeper than {MAX_DEPTH}")
        included = expand(path.read_text(encoding="utf-8"), prompts_dir, _stack + (path,))
        if line.endswith("\n") and not included.endswith("\n"):
            included += "\n"
        out.append(included)
    return "".join(out)
