# Next Steps: KB Maintenance

## Problem summary

KB retrieval quality degrades silently. There are two failure modes:

- **False positive**: a chunk retrieves for a query it shouldn't match. The description is too broad, or phrased in a way that accidentally overlaps with unrelated queries.
- **False negative**: a chunk that should have retrieved didn't. The description doesn't match how a user asks for the technique cold, absent the multi-turn context in which it was originally developed.

Both failures are currently invisible or hard to act on. This document describes changes to address both.

---

## Root cause: description phrasing

The description field is generated at `/learn` time by asking Claude to summarize what the chunk contains. Summary language and query language live in different parts of the vector space. A user working cold will phrase their need as intent ("show me contamination trends by operator") not as a caption ("analysis decomposing contamination flag trends by operator across time"). The embedding key should match the query, not the content.

A secondary issue: a single description per chunk is a single bet. If the user phrases their cold query differently than the one variant that was generated, the chunk misses.

---

## Change 1: Dual description at `/learn` time

**Goal:** Separate the human-readable label ("what it is") from the embedding keys ("how asked"), and generate multiple "how asked" variants per chunk. The number of variants is not fixed — the user can add, remove, or reword them freely before saving.

### What changes

**`claude_handler.py` — `extract_learn_chunks()`**

Claude currently generates one `description` per chunk. Change the output schema to:

```json
{
  "label": "short human-readable summary of what this chunk contains",
  "queries": [
    "how a user might ask for this cold, variant 1",
    "how a user might ask for this cold, variant 2",
    "how a user might ask for this cold, variant 3"
  ],
  "content": "..."
}
```

The prompt should instruct Claude to write `queries` as first-person requests, not captions — the way Huy would type them into Dabble on a fresh session.

**`learn_review.py` — review UI**

Each chunk card shows:
- `label` as the card header (read-only, for human orientation)
- `queries` as an editable list — user can reword, delete, or add variants before saving. No fixed number required.
- `content` in the existing expander

**`knowledge_base.py` — `add_chunk()`**

Store one ChromaDB entry per query variant, all with the same `full_text` in metadata. The `source_file` metadata field already exists and drives the `remove_chunks_by_source` cleanup.

**`knowledge_base.py` — `search()`**

Deduplicate results on `full_text` before returning — the same chunk can match via multiple variants in a single query.

**`.txt` file format**

The `label` goes on the first line (prefixed `label:`), followed by one `query:` line per variant, then the content body. Example:

```
label: Join path for result counts and reportable calls
query: how do I join result counts to reportable calls
query: what table links results to the reportable call
query: show me the join between sequencing results and calls
[content body...]
---
```

`rebuild_from_directory()` parses this format to reconstruct ChromaDB from files.

---

## Change 2: False positive tuning from the provenance block

**Goal:** Let the user reword or remove a query variant in context, at the moment they can see why the match was wrong. Claude suggests a narrower phrasing; the user edits, replaces, or discards it.

### What changes

**Provenance block UI (`conversation.py`)**

Each retrieved chunk in the `📚 N knowledge chunk(s) retrieved` expander gets a "Tune" button alongside its description and similarity score.

Clicking "Tune" opens an inline panel showing:
- The query that triggered the retrieval (read-only)
- The current query variant that matched (read-only)
- The similarity score (read-only)
- Claude's suggested narrower phrasing (editable text input, pre-filled)
- Save / Cancel

The user can edit Claude's suggestion freely, or replace it entirely. They can also delete the variant with no replacement if it was simply wrong.

**Claude prompt for suggested rewording**

```
The following knowledge base query phrasing matched a user query it should not have.

User query: {query}
Matched phrasing: {description}
Similarity: {similarity}
Chunk content: {content}

Suggest a narrower phrasing that would still match the intended use case
but would not match this user query. Return only the replacement phrasing, no explanation.
```

**On save**

Delete the specific ChromaDB entry for the matched variant (by ID), optionally add a new entry with the replacement text and a fresh embedding. The `.txt` file is updated to replace or remove the old `query:` line. Other variants for the same chunk are untouched.

---

## Change 3: False negative recovery from the provenance block

**Goal:** When no knowledge is retrieved, surface near-miss chunks so the user can judge whether a relevant chunk failed to match, and add the current query as a new variant if so.

### What changes

**`knowledge_base.py` — `near_misses()`**

New function: query ChromaDB without applying the similarity threshold, return the top N results regardless of score. Used only for the near-miss display, not for context injection.

**Provenance block UI — "No knowledge retrieved" case**

The existing `📚 No knowledge retrieved` indicator gains a collapsible section: "Near misses — chunks that scored below threshold." Shows the top 3–5 by similarity with:
- The similarity score
- The matched query variant (the embedding key that was closest)
- The chunk content in an expander, so the user can judge actual relevance

Each near-miss gets an "Add variant" button.

**"Add variant" flow**

The current user query is the default new variant — it is literally how the user asked for this cold, which is exactly the failure mode being fixed. One-click adds it with no further input required. Optionally, Claude can suggest a cleaned-up version if the query was long or conversational, but the raw query is a valid default.

On save: new ChromaDB entry added with the user's query as the embedded document; `.txt` file gets a new `query:` line for that chunk.

### Why not show near-misses when chunks were retrieved

When something retrieved, the system appeared to work. Surfacing near-misses in that context would require the user to understand that "retrieved" and "retrieved everything relevant" are different things — too much cognitive load mid-analysis. If this turns out to be a real gap in practice, it can be added later. The two-mode design (tune on false positive, add variant on false negative) should be sufficient to converge the KB toward usefulness through normal use.

---

## Minor addition: `/kb rebuild` command

Add `/kb rebuild` as a sub-command of the existing `/kb` handler. It calls `rebuild_from_directory()` — clears ChromaDB and reloads all chunks from the `.txt` files. Admin escape hatch for resyncing after a crash or manual file edit. One-liner implementation; the function already exists.

---

## What is not changing

- The similarity threshold remains global. Per-chunk thresholds were considered but rejected: a broad description that retrieves falsely at high similarity is still a badly-phrased description. The right fix is rewording, not raising the bar.
- The `label` field is never embedded. It is for human reading only.
- `/kb` diagnostic command is unchanged — still useful for probing retrieval manually.
