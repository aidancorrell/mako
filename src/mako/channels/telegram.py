"""Telegram channel — async Telegram bot using python-telegram-bot."""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from mako.agent import Agent
from mako.context import ContextAssembler
from mako.memory.store import ConversationStore
from mako.providers.base import Message

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096


def _split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit.

    Tries to split on newlines first, then on spaces, then hard-cuts.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a newline
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1 or split_at < max_length // 2:
            # Try to split at a space
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1 or split_at < max_length // 2:
            # Hard cut
            split_at = max_length

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()

    return chunks


class TelegramChannel:
    """Telegram bot channel for Mako."""

    def __init__(
        self,
        token: str,
        agent: Agent,
        store: ConversationStore,
        allowed_chat_ids: list[int] | None = None,
        context: ContextAssembler | None = None,
    ) -> None:
        self.agent = agent
        self.store = store
        self.context = context
        self.allowed_chat_ids = set(allowed_chat_ids) if allowed_chat_ids else None

        # Per-chat session tracking and history
        self._sessions: dict[int, str] = {}  # chat_id -> session_id
        self._histories: dict[int, list[Message]] = {}  # chat_id -> message history

        self._app = Application.builder().token(token).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("new", self._handle_new))
        self._app.add_handler(CommandHandler("reload", self._handle_reload))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

    def _is_allowed(self, chat_id: int) -> bool:
        """Check if a chat is allowed to use the bot."""
        if self.allowed_chat_ids is None:
            return True  # No allowlist = allow all
        return chat_id in self.allowed_chat_ids

    def _get_session(self, chat_id: int) -> str:
        """Get or create a session for a chat."""
        if chat_id not in self._sessions:
            session_id = self.store.create_session(title=f"Telegram chat {chat_id}")
            self._sessions[chat_id] = session_id
            self._histories[chat_id] = []
        return self._sessions[chat_id]

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.message:
            return
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            await update.message.reply_text("Not authorized.")
            logger.warning("Unauthorized /start from chat %d", chat_id)
            return

        self._get_session(chat_id)
        await update.message.reply_text(
            "Hey, I'm Mako. Send me a message and I'll do my best to help.\n\n"
            "/new — start a fresh conversation\n"
            "/reload — reload personality and memory files"
        )

    async def _handle_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.message:
            return
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return

        session_id = self.store.create_session(title=f"Telegram chat {chat_id}")
        self._sessions[chat_id] = session_id
        self._histories[chat_id] = []
        await update.message.reply_text("Fresh start. What's up?")

    async def _handle_reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.message:
            return
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        if self.context is None:
            await update.message.reply_text("Reload not available.")
            return
        self.context.reload()
        logger.info("Reloaded personality/memory files via /reload from chat %d", chat_id)
        await update.message.reply_text("Reloaded personality and memory files.")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.message or not update.message.text:
            return

        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            await update.message.reply_text("Not authorized.")
            return

        session_id = self._get_session(chat_id)
        user_text = update.message.text
        history = self._histories.get(chat_id, [])

        logger.info("Telegram message from chat %d: %s", chat_id, user_text[:100])

        # Send typing indicator
        await update.effective_chat.send_action("typing")

        try:
            response = await self.agent.run(
                user_text, history=history, session_id=str(chat_id),
            )

            # Persist to SQLite
            self.store.save_message(session_id, "user", user_text)
            self.store.save_message(session_id, "assistant", response)

            # Update in-memory history
            history.append(Message(role="user", content=user_text))
            history.append(Message(role="assistant", content=response))
            if len(history) > 40:
                history = history[-30:]
            self._histories[chat_id] = history

            # Send response (split if needed)
            for chunk in _split_message(response):
                await update.message.reply_text(chunk)

        except Exception as e:
            logger.error("Agent error for chat %d: %s", chat_id, e, exc_info=True)
            await update.message.reply_text("Something went wrong. Please try again.")

    async def run(self) -> None:
        """Start the Telegram bot (long-polling)."""
        logger.info("Starting Telegram bot (polling)...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot is running")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        logger.info("Stopping Telegram bot...")
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
