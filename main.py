import datetime
import logging
import os
import traceback
import typing
import aiohttp
from gradio_client import Client as GraioClient
from atproto import AsyncClient as BskyClient
from config import Config
from db.db import Database

import discord
from discord.ext import commands
from dotenv import load_dotenv


class ArtBot(commands.Bot):
    client: aiohttp.ClientSession
    gradio_client: GraioClient
    bsky_client: BskyClient
    config: Config
    db: Database
    _uptime: datetime.datetime = datetime.datetime.now()

    def __init__(self, prefix: str, ext_dir: str, *args: typing.Any, **kwargs: typing.Any) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(*args, **kwargs, command_prefix=commands.when_mentioned_or(prefix), intents=intents)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ext_dir = ext_dir
        self.synced = False
        self.remove_command('help')

    async def _load_extensions(self) -> None:
        if os.getenv("MODE") == "DEV":
            await self.load_extension('jishaku')
        if not os.path.isdir(self.ext_dir):
            self.logger.error(f"Extension directory {self.ext_dir} does not exist.")
            return
        for filename in os.listdir(self.ext_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                try:
                    await self.load_extension(f"{self.ext_dir}.{filename[:-3]}")
                    self.logger.info(f"Loaded extension {filename[:-3]}")
                except commands.ExtensionError:
                    self.logger.error(f"Failed to load extension {filename[:-3]}\n{traceback.format_exc()}")

    async def on_error(self, event_method: str, *args: typing.Any, **kwargs: typing.Any) -> None:
        self.logger.error(f"An error occurred in {event_method}.\n{traceback.format_exc()}")

    async def on_ready(self) -> None:
        self.logger.info(f"Logged in as {self.user} ({self.user.id})")

    async def setup_hook(self) -> None:
        self.client = aiohttp.ClientSession(cookies={'PHPSESSID': os.getenv("PIXIV_COOKIE")},headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0", "Referer": "https://www.pixiv.net/"})
        self.gradio_client = GraioClient("Halfabumcake/camie-test")
        self.config = Config(os.getenv("CONFIG_PATH"))
        self.db = Database(os.getenv("SQLITE_PATH"))
        
        # Initialize Bluesky client if credentials are provided
        bsky_identifier = os.getenv("BLUESKY_IDENTIFIER")
        bsky_password = os.getenv("BLUESKY_APP_PASSWORD")
        if bsky_identifier and bsky_password:
            self.bsky_client = BskyClient()
            await self.bsky_client.login(bsky_identifier, bsky_password)
            self.logger.info("Logged in to Bluesky")
        else:
            self.bsky_client = None
            self.logger.warning("Bluesky credentials not provided, Bluesky support disabled")
        
        await self.db.connect()
        await self._load_extensions()
        if not self.synced:
            await self.tree.sync()
            self.synced = not self.synced
            self.logger.info("Synced command tree")

    async def close(self) -> None:
        await self.client.close()
        await self.gradio_client.close()
        await self.db.close()
        await super().close()

    def run(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        load_dotenv()
        try:
            super().run(str(os.getenv("TOKEN")), *args, **kwargs)
        except (discord.LoginFailure, KeyboardInterrupt):
            self.logger.info("Exiting...")
            exit()

    @property
    def user(self) -> discord.ClientUser:
        assert super().user, "Bot is not ready yet"
        return typing.cast(discord.ClientUser, super().user)

    @property
    def uptime(self) -> datetime.timedelta:
        return datetime.datetime.now() - self._uptime


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    bot = ArtBot(prefix="!", ext_dir="cogs")
    bot.run()


if __name__ == "__main__":
    main()