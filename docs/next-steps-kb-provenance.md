# Next Steps: KB Retrieval Provenance

## Known gap

KB context retrieved for a turn is currently only stored in memory (`turn["kb_descriptions"]`). It is shown in the UI during a live session but lost when the conversation is archived and reloaded.

This is a real gap: the retrieved chunks shaped the LLM's answer for that turn. Without a durable record, you cannot audit why the model responded the way it did.

## What needs to change

1. **`conversation_file.py`** — write a `kb_context:` block to the `.txt` file after each user turn, before the assistant response. Format example:
   ```
   kb_context:
     0.342 — User display preferences for sequencing run queries
     0.581 — Join path for result counts and reportable calls
   ```

2. **`_run_agent` in `conversation.py`** — call the new write function with `kb_descriptions` immediately after `get_kb_context`.

3. **`_messages_to_turns` in `conversation.py`** — parse `kb_context:` blocks out of the `.txt` file on load and attach them to the corresponding assistant turn dicts, so the expander renders correctly for archived conversations.

## Notes

- The `.json` sidecar stores the Anthropic messages list for session resumption. KB retrieval is not part of the API messages and should not be added there — the `.txt` file is the right place.
- The `kb_context:` block belongs to the turn it influenced, so it should appear between the `User:` block and the `Assistant:` block in the `.txt` file.
- Cosine distance values should be included so the `.txt` record is useful for threshold tuning after the fact.
