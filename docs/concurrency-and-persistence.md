# Design note: agent-loop concurrency and durable conversation state

**Status:** Proposal — for review before implementation.
**Scope:** `src/pages/conversation.py`, `src/claude_handler.py`, `src/conversation_file.py`.

## Symptom

Intermittent crash. The Anthropic API rejects a request with:

```
400 invalid_request_error — messages.N: `tool_use` ids were found without
`tool_result` blocks immediately after. Each `tool_use` block must have a
corresponding `tool_result` block in the next message.
```

It is **not reproducible on demand** — it depends on timing — and it has been
observed against conversations that, on disk, are perfectly well-formed.

## Root cause

A mismatch between what the tool loop *is* and what Streamlit *assumes a script
run is*.

Streamlit assumes every script run is **cheap, idempotent, and freely
restartable** — it tears runs down and re-runs them on every widget interaction,
timer, and websocket reconnect. Before the tool loop, `_run_agent` was a single
fast LLM call, so a run was short and the chance of a second run overlapping it
was negligible. "Blocking" was never *enforced* by Streamlit; the call was just
fast enough to look atomic.

The tool loop turned that into a **long (up to several minutes), side-effectful,
non-yielding** operation:

- **Long** — `run_tool_loop` ([claude_handler.py](../src/claude_handler.py)) can
  run many round-trips. The window for another run to overlap is now wide.
- **Non-yielding** — the loop makes **no `st.*` call** in its body; it only
  appends to a list and calls the Anthropic SDK. Streamlit signals a run to stop
  *at its next `st.*` call*, so this loop never observes the stop signal. When a
  rerun/reconnect arrives, the old thread keeps running while a new one starts —
  two concurrent threads in the **same session**.
- **Shared mutable state** — `_run_agent` calls `run_tool_loop(st.session_state.messages)`,
  which mutates that list **in place**. `pending_input` is cleared only *after*
  the loop returns ([conversation.py:40-43](../src/pages/conversation.py)), so the
  second thread re-enters `_run_agent` and both threads append to the same list.

Interleaved appends place an `assistant`(tool_use) message next to something
other than its `tool_result`, violating the API's adjacency rule → the 400 on the
next send.

### Why we are confident it is a race, not a deterministic bug

The corruption **was never written to disk**. The conversation that crashed froze
at its last cleanly-completed turn; the corrupting turn's messages were never
persisted, and the offending `tool_use` id appears in no saved file. This
distinguishes the two candidate causes:

| Candidate | Saves a dangling `tool_use` to disk? |
|---|---|
| **Truncation** (`stop_reason == "max_tokens"` with a tool_use present; loop breaks at [claude_handler.py:411](../src/claude_handler.py) and returns *normally*, so `save_messages` runs) | **Yes** — would be visible on disk |
| **Concurrency race** (both threads crash on `messages.create`; `_run_agent` raises before `save_messages`) | **No** — corruption stays in memory |

On-disk state is clean everywhere → truncation is ruled out, race confirmed. It
follows that the two threads shared one `session_state.messages` (a single
interleaved request can only arise from one shared list), so a session-scoped
lock is provably in the path.

This is strictly an **intra-session** bug. `st.session_state` is per-session, so
two *different users* cannot corrupt each other's messages. A single user, alone,
triggers it whenever a rerun lands inside the in-flight `_run_agent`.

## Invariant to enforce

> The conversation message list transitions only between **complete, valid
> states**: every `assistant`(tool_use) is immediately followed by a user message
> containing the matching `tool_result`. This must hold both in memory and on
> disk, and must be preserved under concurrent script runs and under process
> restart.

## Options considered

1. **Yielding / generator loop.** Make `run_tool_loop` a generator that yields
   after each round-trip; drive it from `@st.fragment` / `st.write_stream`. The
   loop becomes a cooperative Streamlit citizen — it yields, so Streamlit can
   observe stops, stream tool results incrementally, and never spawn an
   overlapping thread. *Fixes responsiveness and overlap; in-process.*

2. **Background worker owns the conversation.** `_run_agent` hands work to a
   thread/queue that owns `messages` and the file; script runs just render and
   poll. *Most aligned with Streamlit's model; largest change.*

3. **Durable append-only log + file lock as source of truth.** Persist each
   completed turn to an append-only log, guard the agent run with an OS file lock.
   *Fixes corruption + restart survival + multi-process safety; does not address
   responsiveness.*

These are **orthogonal**, not exclusive. (3) buys durability/robustness; (1) buys
responsiveness. (3)'s lock also makes a later (1) safe in the interim.

## Proposed direction

Adopt **(3) now**, structured so **(1)** can follow later without rework.

### Immediate (stops the production crash)

1. **Re-entrancy guard around the agent run.** Acquire a lock before running the
   loop; if it is already held, do nothing (another thread of this session is
   already answering). Clear `pending_input` *before* running.

   Use an OS file lock (`fcntl.flock`) rather than `threading.Lock`, because it
   also covers the multi-process window (a restart wrapper, or two processes
   briefly overlapping during a restart). Key details:
   - **Open a fresh fd per acquisition.** flock locks are per *open file
     description*, so independently-opened fds — across threads *and* processes —
     arbitrate against each other.
   - **Agent run: non-blocking, bail** (`LOCK_EX | LOCK_NB`, skip if held). Do
     **not** block here — blocking would just queue a duplicate multi-minute run.
   - **Short appends: a brief blocking lock is fine.**
   - flock is released automatically when the process dies, so a killed/restarted
     process leaves **no stale lock** (no PID-reaping logic needed).
   - Single-host only (fine for the current deployment; not NFS-safe).

2. **Atomic turn persistence as an append-only log.** Replace the full-rewrite
   JSON sidecar with a **JSONL** log (one message object per line), appended at
   **turn granularity** — only once the turn is complete and valid (after the
   `tool_result` exists).

   - Append **per turn, not per message.** Per-message appends would write a
     dangling `tool_use` to disk if a crash lands between the assistant line and
     the tool_result line — re-introducing exactly the corruption we are
     eliminating, and forcing a load-time repair step. The `.txt` transcript
     already appends at turn granularity ([conversation.py:292-300](../src/pages/conversation.py));
     the JSON full-rewrite ([conversation_file.py:166-175](../src/conversation_file.py))
     is the only non-append-only writer, so this is a contained change.
   - `load_messages` reads and parses lines instead of one blob.

### Enables: restart wrapper

With conversation state durable in the append-only log, the Streamlit process
becomes **disposable**: a crash or restart loses at most the single in-flight
turn, never the conversation. A supervisor (systemd, or the existing `start.sh`
pattern) can restart it safely, and flock's auto-release means an overlapping
restart cannot corrupt or deadlock.

### Lite vs. full (a real decision to make)

- **Lite (recommended default):** keep `session_state.messages` as the working
  copy; append completed turns to the log; read the log back only on initial load
  (already done). Safe **because the lock guarantees a single writer per
  session**, so the in-memory copy cannot diverge from disk within a session.
- **Full (event-sourced):** the log is the *only* source of truth; rebuild
  `session_state.messages` from it on **every** run.

The only case Lite does not cover is the **same conversation open in two tabs**
(two sessions → two in-memory copies → both appending to one log → logical
interleave). Note this is **already broken today** (both tabs full-rewrite the
JSON, last-write-wins), so Lite does not regress it — only Full fixes it. Choose
Full only if same-conversation multi-tab/multi-process is a requirement.

### Deferred: responsiveness (option 1)

A yielding/generator loop remains the durable fix for the 5-minute spinner, lack
of streaming, and spend on abandoned runs. It is independent of this work and can
be scheduled later; the lock makes the interim safe.

## What this fixes / does not fix

**Fixes:** the intermittent 400 (corruption); loss of conversation state on
crash/restart; concurrent-write safety across threads and processes.

**Does not fix:** UI responsiveness during a long turn; tool-result streaming;
billing for runs the user has navigated away from; stale in-memory chart media
across reruns (the `MediaFileStorageError` class — a related instance of
long-lived state living in a disposable place, addressed separately).

## Open questions

- Is same-conversation multi-tab a real usage pattern? (Decides Lite vs. Full.)
- Do we want the deferred option (1) on the roadmap now, or only if responsiveness
  complaints arise?
- Should `run_tool_loop`'s `stop_reason != "tool_use"` branch
  ([claude_handler.py:411](../src/claude_handler.py)) also explicitly handle a
  `max_tokens` stop that still carries a tool_use? Not implicated in this
  incident, but it is a latent way to persist a dangling tool_use independent of
  the race.
