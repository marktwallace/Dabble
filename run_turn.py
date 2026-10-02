"""Run one conversation turn without the browser.

    uv run python run_turn.py "question"                          # new conversation
    uv run python run_turn.py --conversation conversations/X.txt "follow-up"
    uv run python run_turn.py --prompts-dir /path/to/prompts "question"

Builds the same system prompt, database connection and tools as the app, runs
the tool loop once, and writes the conversation's .txt and .json files where
the app does, so the conversation opens in the app afterwards. Prints the
conversation path and the final reply.

Do not add a turn to a conversation that is open in a browser: that session
does not see the new turn and overwrites the files on its next turn.
Slash commands and attachments are not supported.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
    force=True,
)

from src import conversation_file as conv_file  # noqa: E402
from src.agent_session import build_system_prompt, prepend_title, replay_tool_calls, write_new_messages  # noqa: E402
from src.claude_handler import ClaudeHandler, response_text  # noqa: E402
from src.duckdb_analytic import DuckDBAnalytic  # noqa: E402
from src.session import SessionState  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Dabble conversation turn without the browser.")
    parser.add_argument("text", help="The user's message.")
    parser.add_argument("--conversation", help="Existing conversation .txt to continue. Omit to start a new one.")
    parser.add_argument("--prompts-dir", default=os.environ.get("PROMPTS_DIR", "prompts"),
                        help="Directory holding system_prompt.md (default: PROMPTS_DIR).")
    args = parser.parse_args()

    text = args.text.strip()
    if not text or text.startswith("/"):
        print("Error: give a plain message; slash commands are not supported.", file=sys.stderr)
        return 2

    if args.conversation:
        path = args.conversation
        if not Path(path).exists():
            print(f"Error: no conversation at {path}", file=sys.stderr)
            return 2
    else:
        conversations_dir = os.environ.get("CONVERSATIONS_DIR", "conversations")
        Path(conversations_dir).mkdir(parents=True, exist_ok=True)
        path = conv_file.new_path(conversations_dir)
        if Path(path).exists():
            # new_path names files to the minute; never write into another conversation.
            print(f"Error: {path} already exists; try again in a minute.", file=sys.stderr)
            return 2

    db = None
    if os.environ.get("DABBLE_S3_BUCKET") or os.environ.get("DABBLE_DATA_PATH") or os.environ.get("DUCKDB_ANALYTIC_FILE"):
        db = DuckDBAnalytic()

    knowledge_dir = os.environ.get("KNOWLEDGE_DIR", "knowledge")
    state = SessionState(analytic_db=db)
    handler = ClaudeHandler(build_system_prompt(args.prompts_dir, db), knowledge_dir, state, args.prompts_dir)

    messages = conv_file.load_messages(path) if args.conversation else []
    replay_tool_calls(messages, handler)
    is_first = not messages

    conv_file.append_user(path, text)
    messages.append({"role": "user", "content": text})
    prev_len = len(messages)

    rate_limited = False
    try:
        messages, response = handler.run_tool_loop(messages)
    except anthropic.RateLimitError:
        # As in the app: run_tool_loop appends in place, so messages holds every
        # round-trip that completed; save those and stop.
        response, rate_limited = None, True
    new_messages = messages[prev_len:]

    if is_first:
        prepend_title(path, handler.generate_title(text))
    write_new_messages(path, new_messages)
    conv_file.save_messages(path, messages)

    print(path)
    if rate_limited:
        print("(The API rate limit was reached; the turn stopped early.)")
        return 1
    if getattr(response, "stop_reason", None) == "refusal":
        print("(The model declined this request.)")
        return 1
    print(response_text(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
