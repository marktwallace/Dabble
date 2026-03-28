# Plan: KB maintenance via conversation

## What this adds

Two new Claude tools — `update_knowledge` and `delete_knowledge` — that let the analyst
manage the knowledge base through ordinary conversation after `/kb`. No new slash commands.

---

## New tools

### `update_knowledge(slug, description, content)`

Creates or overwrites `knowledge/<slug>.txt`. If `slug` is omitted or empty, derives one
from the description using the existing `slug_from_description()` logic. Reuses
`write_chunk()` from `knowledge_base.py`.

Claude uses this for: updating an existing chunk, writing a merged replacement,
creating a new chunk mid-conversation (without going through `/learn`).

### `delete_knowledge(slug)`

Removes `knowledge/<slug>.txt`. Returns a clear error if the slug doesn't exist.

Claude uses this for: removing a stale chunk, cleaning up after a merge (write the merged
version first, then delete the originals).

---

## UX changes

### `/kb` output

Add a `st.caption` below the registry table:

> Ask Claude to update, merge, or delete any of these — or ask for a full cleanup pass.

This makes the maintenance path discoverable without adding a command.

### `/learn` confirmation screen

Add a `st.caption` after the save button (shown after saving, or always):

> Saved. If any of these overlap with existing chunks, ask Claude to merge them — type `/kb` to review.

---

## Session-state behaviour

Tool writes take effect on disk immediately. The in-session `<available_knowledge>` registry
(baked into the system prompt at handler init) is **not** updated mid-conversation — the
same constraint as `/learn`. Claude should acknowledge this when it makes changes:
"Updated. The revised chunk will be in the registry from your next conversation."

This is acceptable: KB maintenance is an administrative act, not part of an active analysis.
The analyst is not expected to immediately query new/updated chunks in the same session.

---

## What Claude can do with just these two tools

| Request | How Claude handles it |
|---|---|
| "Delete the X chunk" | `delete_knowledge("x")` |
| "Update X with the SQL we just found" | `recall_knowledge("x")` → edit → `update_knowledge(...)` |
| "Tighten the description on X" | `recall_knowledge("x")` → rewrite description → `update_knowledge(...)` |
| "Merge X and Y" | recall both → synthesise → `update_knowledge(merged)` → `delete_knowledge` the spare |
| "Resolve the conflict between X and Y" | recall both → propose resolution → act after analyst confirms |
| "Do a full cleanup pass" | recall all chunks → propose restructured set → analyst reviews → Claude writes |

The "full cleanup" case may involve many tool calls. Claude should narrate what it's doing
and ask for confirmation before bulk-deleting anything.

---

## Files changed

| File | Change |
|---|---|
| `src/knowledge_base.py` | Add `delete_chunk(slug, knowledge_dir)` |
| `src/claude_handler.py` | Add `update_knowledge` and `delete_knowledge` to `_tools()` and `_execute_tool()` |
| `src/pages/conversation.py` | Add `st.caption` to `/kb` output |
| `src/pages/learn_review.py` | Add `st.caption` after save |

---

## Open questions

1. **Slug collision on `update_knowledge`:** If Claude passes a slug that already exists,
   the intent is to overwrite. `write_chunk()` currently generates a unique slug to avoid
   collision. For `update_knowledge`, overwrite should be the default — bypass the
   uniqueness check and write directly to `knowledge/<slug>.txt`.

2. **Confirmation for bulk deletes:** For single-chunk deletes, the tool call in the
   expander is sufficient audit trail. For a cleanup pass deleting 3+ chunks, Claude should
   list what it plans to remove and wait for explicit approval before calling
   `delete_knowledge` in bulk.
