# Plan: concurrency fix (two steps)

Companion to [concurrency-and-persistence.md](concurrency-and-persistence.md)
(the why). This is the **what we will actually do**. Two independent steps;
**Step 1 stops the crash**, Step 2 adds durability. Ship Step 1 first.

Decisions already made:
- **Lite** — in-memory `messages` stays the working copy.
- **Lock matched to the concurrency boundary at each step.** Step 1 uses an
  in-process `threading.Lock` (the crash is intra-process: two threads, one
  Streamlit process, one shared `session_state`). Step 2 swaps to `fcntl.flock`
  only when the restart wrapper introduces a *process*-level boundary. Don't
  reach for an IPC primitive before there is IPC.
- Option 1 (yielding loop) is out of scope.

---

## Step 1 — Re-entrancy lock (the crash fix)

**Goal:** make it impossible for two `_run_agent` runs of the same conversation
to execute concurrently. This eliminates the interleaved-append race that
produces the `tool_use` / `tool_result` 400.

**No storage-format change. No disk artifacts. No UI change in the normal path.**
The only changed behavior: a second run started while one is in flight now
*bails* instead of running (and corrupting).

### Change 1.1 — create the lock in `src/pages/conversation.py`

Add `import threading` at the top. In `_init_session`, inside the existing
`if st.session_state.get("_active_path") != path:` block (alongside
`dataframes`/`figures`, [conversation.py:122-147](../src/pages/conversation.py)),
create one lock per loaded conversation:

```python
        st.session_state._run_lock = threading.Lock()
```

Creating it in that guarded block (which runs once per conversation load, before
any `pending_input` can exist) means both concurrent threads of the session read
the *same* lock object from `session_state` — no lazy-creation race.

### Change 1.2 — guard the run in `src/pages/conversation.py`

Replace the current block ([conversation.py:40-43](../src/pages/conversation.py)):

```python
    if st.session_state.get("pending_input"):
        _run_agent(st.session_state.pending_input)
        st.session_state.pending_input = None
        st.rerun()
```

with:

```python
    if st.session_state.get("pending_input"):
        lock = st.session_state._run_lock
        if lock.acquire(blocking=False):
            try:
                pending = st.session_state.pending_input
                st.session_state.pending_input = None   # clear before running
                _run_agent(pending)
            finally:
                lock.release()
            st.rerun()
        # else: another run for this conversation is in progress — do nothing.
        # pending_input stays set and is processed on the next rerun, after the
        # holder finishes and calls st.rerun().
```

Two deliberate changes vs. today:
- **Clear `pending_input` before the loop**, not after — removes the re-trigger.
- **Bail if the lock is held** (`acquire(blocking=False)`) — the second
  concurrent run does nothing instead of mutating the shared `messages` list. Not
  blocking, so a second attempt never queues behind a multi-minute run.

No changes to `conversation_file.py` or `claude_handler.py` in this step.

### Validation (Step 1)

- **Unit:** on one lock, `acquire(blocking=False)` returns `True`, a second call
  returns `False`; after `release()`, the next call returns `True` again.
- **Behavioral, local:** run the app, start a long question, and force a rerun
  mid-run (interact with a widget / re-submit). Confirm: no 400, the second
  action is ignored, and the first answer completes and renders.
- **Regression:** a normal single question still works end to end.

### Risk / rollback

Self-contained: one import, one line in `_init_session`, one edited block. No
new files, no format change, no migration, cross-platform. Rollback = revert
those edits.

---

## Step 2 — Append-only JSONL log (durability + restart wrapper)

**Goal:** make conversation state survive process restart, so the Streamlit
process can run under a restart supervisor. Independent of Step 1; do after
Step 1 is validated.

**This step carries the only real format change (`.json` → `.jsonl`) and the
move to a process-level lock.**

### 2a — Swap the lock to `fcntl.flock`

The restart wrapper makes two *processes* possible (brief overlap during a
restart, or a supervisor that relaunches). A `threading.Lock` cannot span
processes, so replace the Step 1 guard with a file lock keyed on the conversation.

Add to `src/conversation_file.py` (`import os`; guard the `import fcntl` so the
OSS app still imports on Windows — the restart wrapper is a Unix-deployment
feature):

```python
def acquire_run_lock(path: str):
    """Non-blocking exclusive lock for the agent run of one conversation.

    Returns an open fd on success, or None if already held (by another thread of
    this process, or another process). flock is keyed on the open file
    description, so a freshly-opened fd arbitrates across both threads and
    processes. Released automatically if the process dies — no stale locks.
    """
    lock_path = str(Path(path).with_suffix(".lock"))
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def release_run_lock(fd) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
```

Then the guard in `conversation.py` uses `conv_file.acquire_run_lock(...)` /
`release_run_lock(...)` in place of the `threading.Lock` (same bail-if-held
shape). flock with a per-acquisition fresh fd covers the intra-process threads
too, so it fully replaces the Step 1 lock — single mechanism, no layering. Add
`conversations/*.lock` to `.gitignore`.

### 2b — Append-only JSONL log

1. **Write the log append-only at turn granularity.** Replace the full-rewrite
   `save_messages` ([conversation_file.py:166-175](../src/conversation_file.py))
   with an append of the *new* turn's messages, one JSON object per line, to a
   `.jsonl` sidecar. Append only after the turn is complete and valid (the
   `tool_result` exists) — never per message — so a crash can never leave a
   dangling `tool_use` on disk. `_run_agent` already isolates the new turn as
   `new_messages = messages[prev_len:]`
   ([conversation.py:292-300](../src/pages/conversation.py)), so that is the
   batch we append. Keep the existing image-stripping (`_strip_image_data`)
   applied per appended message.

2. **Read the log, with legacy fallback.** `load_messages` reads and parses
   `.jsonl` lines. If only the legacy `.json` exists, read that (decide
   migrate-on-load vs. leave-legacy when we start the step).

### Enables

A restart wrapper (systemd / existing `start.sh` pattern). With state durable in
the append-only log, a crash/restart loses at most the in-flight turn; flock's
auto-release means an overlapping restart cannot corrupt or deadlock.

### Validation (Step 2)

- Lock: two `acquire_run_lock(path)` calls → first returns an fd, second `None`;
  after `release_run_lock`, a third returns an fd.
- Round-trip: a conversation written as `.jsonl` reloads identically.
- Legacy: an existing `.json` conversation still loads.
- Crash-mid-turn: kill the process during a turn → on restart the conversation
  loads cleanly at the last completed turn, with no dangling `tool_use`.

### Out of scope (both steps)

UI responsiveness during a long turn, tool-result streaming, cancelling
abandoned runs, stale chart media across reruns. These need option 1 (yielding
loop) and are tracked separately.
