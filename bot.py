import logging
import os
import platform

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.helpers.SimplePointsManager import PointsManagerSingleton
from cogs import EXTENSIONS

intents = discord.Intents.default()


class LoggingFormatter(logging.Formatter):
    # Colors
    black = "\x1b[30m"
    red = "\x1b[31m"
    green = "\x1b[32m"
    yellow = "\x1b[33m"
    blue = "\x1b[34m"
    gray = "\x1b[38m"
    # Styles
    reset = "\x1b[0m"
    bold = "\x1b[1m"

    COLORS = {
        logging.DEBUG: gray + bold,
        logging.INFO: blue + bold,
        logging.WARNING: yellow + bold,
        logging.ERROR: red,
        logging.CRITICAL: red + bold,
    }

    def format(self, record):
        log_color = self.COLORS[record.levelno]
        format = "(black){asctime}(reset) (levelcolor){levelname:<8}(reset) (green){name}(reset) {message}"
        format = format.replace("(black)", self.black + self.bold)
        format = format.replace("(reset)", self.reset)
        format = format.replace("(levelcolor)", log_color)
        format = format.replace("(green)", self.green + self.bold)
        formatter = logging.Formatter(format, "%Y-%m-%d %H:%M:%S", style="{")
        return formatter.format(record)


logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(LoggingFormatter())
# File handler
file_handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
file_handler_formatter = logging.Formatter(
    "[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"
)
file_handler.setFormatter(file_handler_formatter)

# Add the handlers
logger.addHandler(console_handler)
logger.addHandler(file_handler)


class DiscordBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents
        )
        self.logger = logger
        self._connected = False

        self.points_manager = PointsManagerSingleton(
            base_url=os.getenv("API_BASE_URL"),
            api_key=os.getenv("API_KEY"),
            realm_id=os.getenv("REALM_ID")
        )

    async def load_cogs(self) -> None:
        """
        The code in this function is executed whenever the bot will start.
        """
        for file in os.listdir(f"{os.path.realpath(os.path.dirname(__file__))}/cogs"):
            if file.endswith(".py"):
                extension = file[:-3]
                try:
                    await self.load_extension(f"cogs.{extension}")
                    self.logger.info(f"Loaded extension '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    self.logger.error(
                        f"Failed to load extension {extension}\n{exception}"
                    )

    async def setup_hook(self) -> None:
        """
        This will just be executed when the bot starts the first time.
        """
        self.logger.info(f"Logged in as {self.user.name}")
        self.logger.info(f"discord.py API version: {discord.__version__}")
        self.logger.info(f"Python version: {platform.python_version()}")
        self.logger.info(
            f"Running on: {platform.system()} {platform.release()} ({os.name})"
        )
        self.logger.info("-------------------")
        for cog in EXTENSIONS:
            await self.load_extension(cog)

    async def on_ready(self) -> None:
        """|coro|

        Overriding :meth:`~discord.Client.on_ready`, to do some basic connect/reconnect info
        """
        await self.wait_until_ready()
        await self.tree.sync()
        if not self._connected:
            self.logger.info("Bot is ready!" + self.user.name)
            self.logger.info("synced!")
        else:
            self.logger.info("Bot reconnected.")

    async def close(self) -> None:
        """
        This is called when the bot is shutting down.
        Clean up the points manager session.
        """
        await self.points_manager.cleanup()
        await super().close()


load_dotenv()

bot = DiscordBot()
bot.run(os.getenv("TOKEN"))