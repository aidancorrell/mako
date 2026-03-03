"""CLI channel — async terminal REPL for local dev/testing."""

import asyncio
import logging

from mako.agent import Agent
from mako.memory.store import ConversationStore
from mako.providers.base import Message

logger = logging.getLogger(__name__)


async def run_cli(agent: Agent, store: ConversationStore) -> None:
    """Run an interactive CLI chat session with persistent history."""
    print("🦈 Mako CLI — type 'quit' or Ctrl+C to exit")
    print("  /new     — start a new session")
    print("  /history — list past sessions\n")

    session_id = store.create_session(title="CLI session")
    history: list[Message] = []

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("you> ")
            )
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye.")
            break

        # CLI commands
        if user_input == "/new":
            session_id = store.create_session(title="CLI session")
            history = []
            print("\n[Started new session]\n")
            continue

        if user_input == "/history":
            sessions = store.list_sessions()
            if not sessions:
                print("\n[No sessions yet]\n")
            else:
                print()
                for s in sessions:
                    print(f"  {s['id'][:8]}... — {s['message_count']} messages — {s['title']}")
                print()
            continue

        try:
            response = await agent.run(user_input, history=history)
            print(f"\nmako> {response}\n")

            # Save to persistent store
            store.save_message(session_id, "user", user_input)
            store.save_message(session_id, "assistant", response)

            # Keep in-memory history for this session
            history.append(Message(role="user", content=user_input))
            history.append(Message(role="assistant", content=response))

            # Trim in-memory history to avoid context overflow
            if len(history) > 40:
                history = history[-30:]

        except Exception as e:
            logger.error("Agent error: %s", e, exc_info=True)
            print(f"\n[Error: {e}]\n")
