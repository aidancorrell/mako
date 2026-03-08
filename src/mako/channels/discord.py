"""Discord channel — async Discord bot using discord.py."""

import logging

import discord
from discord import app_commands

from mako.agent import Agent
from mako.channels.common import split_message
from mako.context import ContextAssembler
from mako.memory.store import ConversationStore
from mako.providers.base import Message

logger = logging.getLogger(__name__)

DISCORD_MAX_LENGTH = 2000


class DiscordChannel:
    """Discord bot channel for Mako (DMs only)."""

    def __init__(
        self,
        token: str,
        agent: Agent,
        store: ConversationStore,
        allowed_user_ids: list[int] | None = None,
        context: ContextAssembler | None = None,
    ) -> None:
        self.token = token
        self.agent = agent
        self.store = store
        self.context = context
        self.allowed_user_ids = set(allowed_user_ids) if allowed_user_ids else None

        # Per-user session tracking and history
        self._sessions: dict[int, str] = {}  # user_id -> session_id
        self._histories: dict[int, list[Message]] = {}  # user_id -> message history

        intents = discord.Intents.default()
        intents.dm_messages = True
        intents.message_content = True

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

        self._register_commands()
        self._register_events()

    def _is_allowed(self, user_id: int) -> bool:
        if self.allowed_user_ids is None:
            return True
        return user_id in self.allowed_user_ids

    def _get_session(self, user_id: int) -> str:
        if user_id not in self._sessions:
            session_id = self.store.create_session(title=f"Discord user {user_id}")
            self._sessions[user_id] = session_id
            self._histories[user_id] = []
        return self._sessions[user_id]

    def _register_commands(self) -> None:
        @self.tree.command(name="start", description="Start a conversation with Mako")
        async def start_command(interaction: discord.Interaction) -> None:
            await self._handle_start(interaction)

        @self.tree.command(name="new", description="Start a fresh conversation")
        async def new_command(interaction: discord.Interaction) -> None:
            await self._handle_new(interaction)

        @self.tree.command(name="reload", description="Reload personality and memory files")
        async def reload_command(interaction: discord.Interaction) -> None:
            await self._handle_reload(interaction)

    def _register_events(self) -> None:
        @self.client.event
        async def on_ready() -> None:
            logger.info("Discord bot logged in as %s", self.client.user)
            await self.tree.sync()
            logger.info("Discord slash commands synced")

        @self.client.event
        async def on_message(message: discord.Message) -> None:
            await self._on_message(message)

    async def _handle_start(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        if not self._is_allowed(user_id):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            logger.warning("Unauthorized /start from Discord user %d", user_id)
            return

        self._get_session(user_id)
        await interaction.response.send_message(
            "Hey, I'm Mako. Send me a message and I'll do my best to help.\n\n"
            "/new — start a fresh conversation\n"
            "/reload — reload personality and memory files"
        )

    async def _handle_new(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        if not self._is_allowed(user_id):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return

        session_id = self.store.create_session(title=f"Discord user {user_id}")
        self._sessions[user_id] = session_id
        self._histories[user_id] = []
        await interaction.response.send_message("Fresh start. What's up?")

    async def _handle_reload(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        if not self._is_allowed(user_id):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        if self.context is None:
            await interaction.response.send_message("Reload not available.")
            return
        self.context.reload()
        logger.info("Reloaded personality/memory files via /reload from Discord user %d", user_id)
        await interaction.response.send_message("Reloaded personality and memory files.")

    async def _on_message(self, message: discord.Message) -> None:
        # Ignore own messages
        if message.author == self.client.user:
            return

        # Only respond to DMs
        if not isinstance(message.channel, discord.DMChannel):
            return

        # Ignore empty messages
        if not message.content:
            return

        user_id = message.author.id
        if not self._is_allowed(user_id):
            await message.channel.send("Not authorized.")
            return

        session_id = self._get_session(user_id)
        user_text = message.content
        history = self._histories.get(user_id, [])

        logger.info("Discord message from user %d: %s", user_id, user_text[:100])

        async with message.channel.typing():
            try:
                response = await self.agent.run(
                    user_text, history=history, session_id=str(user_id),
                )

                # Persist to SQLite
                self.store.save_message(session_id, "user", user_text)
                self.store.save_message(session_id, "assistant", response)

                # Update in-memory history
                history.append(Message(role="user", content=user_text))
                history.append(Message(role="assistant", content=response))
                if len(history) > 40:
                    history = history[-30:]
                self._histories[user_id] = history

                # Send response (split if needed)
                for chunk in split_message(response, DISCORD_MAX_LENGTH):
                    await message.channel.send(chunk)

            except Exception as e:
                logger.error("Agent error for Discord user %d: %s", user_id, e, exc_info=True)
                await message.channel.send("Something went wrong. Please try again.")

    async def send_message(self, user_id: int, text: str) -> None:
        """Send a DM to a user (used by scheduler)."""
        user = await self.client.fetch_user(user_id)
        dm_channel = await user.create_dm()
        for chunk in split_message(text, DISCORD_MAX_LENGTH):
            await dm_channel.send(chunk)

    async def run(self) -> None:
        """Start the Discord bot."""
        logger.info("Starting Discord bot...")
        await self.client.start(self.token)

    async def stop(self) -> None:
        """Stop the Discord bot."""
        logger.info("Stopping Discord bot...")
        await self.client.close()
