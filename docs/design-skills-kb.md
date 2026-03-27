# Design: Replace ChromaDB with Skills-Pattern Knowledge Base

## What changes and why

The current KB uses ChromaDB + sentence-transformers for semantic search. Routing quality
depends on cosine similarity — an unconditional proximity measure that can miss or misfire.
The skills pattern routes via Claude's attention over a registry injected into the system
prompt: conditional on the actual query, no ML infrastructure required.

Removes: `chromadb`, `sentence-transformers`, `scikit-learn`, `scipy` from dependencies.

---

## Knowledge storage

Each chunk is a standalone `.txt` file in `knowledge/`. Filename is a human-readable slug
derived from the description (e.g. `qc-status-codes.txt`). File format is unchanged:

```
description: QC result status codes — meanings of 0, 1, 2 in the qc_status field
<blank line>
Full chunk content here. Can be multi-line. May include SQL examples,
domain corrections, join patterns, etc.
```

The description line is the routing signal — it must be written to fire on the right queries
and not on the wrong ones. The `/learn` extraction prompt should be explicit about this.

**Why one file per chunk (not multi-chunk files with `---` separators):**
The tool call references a specific chunk by filename. Multi-chunk files have no natural
per-chunk address. One file per chunk is also easier to inspect, edit, and delete.

---

## Registry injection

At session start, `knowledge_base.py` scans `knowledge/*.txt`, reads the `description:`
line from each file, and builds a registry block. This is injected into the system prompt
after the schema block:

```
<available_knowledge>
qc-status-codes: QC result status codes — meanings of 0, 1, 2 in the qc_status field
join-fact-results-samples: Standard join between fact_results and dim_samples via sequencing_run_id
contamination-run-10891: Run 10891 had index contamination — exclude from cross-run comparisons
</available_knowledge>
```

If `knowledge/` is empty or `KB_PATH` is unset, the block is omitted entirely.

The system prompt should instruct Claude: *"Before querying an unfamiliar table or answering
a domain question, check `<available_knowledge>` and call `recall_knowledge` for any
relevant entries."*

---

## `recall_knowledge` tool

Added to the tool list in `claude_handler.py`:

```python
{
    "name": "recall_knowledge",
    "description": (
        "Retrieve a domain knowledge chunk by name. "
        "Call this when the available_knowledge registry lists an entry relevant to your current task. "
        "Returns the full chunk content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chunk": {
                "type": "string",
                "description": "The chunk name from the available_knowledge registry (e.g. 'qc-status-codes')."
            }
        },
        "required": ["chunk"]
    }
}
```

Dispatch in the tool handler reads `knowledge/{chunk}.txt` and returns its content.
If the file doesn't exist, returns a clear error so Claude can recover.

The tool call and its result appear in the conversation transcript — visible to the user,
auditable, and included in `/snapshot` outputs.

---

## `/learn` changes

Currently: LLM extracts chunks → `add_chunk()` → ChromaDB (embed + store).

New: LLM extracts chunks → write each chunk to `knowledge/<slug>.txt`.

The extraction prompt needs one addition: ask Claude to write the description line as a
routing classifier, not just a summary. Something like:

> "Write the description line to complete this sentence: 'Recall this chunk when the user
> asks about ___.' It should be specific enough to not fire on unrelated queries."

The slug is derived from the description: lowercase, spaces to hyphens, strip punctuation,
truncate at 50 chars. Collision handling: append `-2`, `-3`, etc.

`/learn` currently shows a confirmation UI before saving. That stays unchanged — the only
difference is the save target.

---

## Session start flow (before vs. after)

**Before:**
1. Load system prompt
2. Inject schema
3. *(KB search happens per-query, proactively, before each tool loop)*

**After:**
1. Load system prompt
2. Inject schema
3. Inject `<available_knowledge>` registry (descriptions only, one line per chunk)
4. *(Claude calls `recall_knowledge` during tool loop when it decides it needs a chunk)*

---

## Migration

Existing ChromaDB data in `knowledge_base/` is abandoned — not migrated. The content
already lives in `knowledge/*.txt` files (that's what `rebuild_from_directory` reads).
On first startup after the change, the registry is built from those files directly.

If `knowledge/` is empty on an instance, behavior is unchanged from today's empty-KB case:
no registry block, `recall_knowledge` is available but never called.

**One-time action on EC2:** `rm -rf ~/agent-dimensional*/db/knowledge_base` — the sqlite
directory is no longer read or written.

---

## Files changed

| File | Change |
|------|--------|
| `src/knowledge_base.py` | Rewrite: remove ChromaDB, add `list_registry()`, `read_chunk()`, `write_chunk()`, `slug_from_description()` |
| `src/claude_handler.py` | Add `recall_knowledge` to `_tools()`; dispatch in tool handler; replace `get_kb_context()` call with registry injection at session start |
| `src/pages/conversation.py` | Remove `get_kb_context()` call; registry is now in system prompt, not per-query |
| `src/pages/learn.py` | Change save target from `add_chunk()` to `write_chunk()` |
| `pyproject.toml` | Remove `chromadb`, `sentence-transformers`, `scikit-learn`, `scipy` |

`numpy` stays — used by `run_python` tool. `boto3` stays — used for S3/DuckLake.

---

## Open questions for review

1. **Description quality gate in `/learn`:** Should the UI show the description line
   separately and ask Huy to approve/edit it before saving? The description is now the
   routing function — worth a moment of attention.

2. **Registry size limit:** If the KB grows to 50+ chunks, the registry block becomes
   non-trivial. No action needed now, but worth knowing the threshold (~50 short descriptions
   ≈ ~1K tokens — manageable for a long time).

3. **Existing `knowledge/*.txt` files:** These are currently multi-chunk files (multiple
   chunks per file, separated by `---`). The new design is one file per chunk. The migration
   needs to split existing multi-chunk files into individual files. Should this happen
   automatically on first startup, or as a one-time manual step?
