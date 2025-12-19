import datetime
import logging
import os
import traceback
import typing
import aiohttp
import json
from twikit import Client as TwitterClient
from gradio_client import Client as GraioClient

import discord
from discord.ext import commands
from dotenv import load_dotenv


class CustomBot(commands.Bot):
    client: aiohttp.ClientSession
    twitterClient = TwitterClient
    gradioClient = GraioClient("Halfabumcake/camie-test")
    webhooks = {}
    char_map = {}
    series_map = {}
    safety_map = {}
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
        cookie = os.getenv("PIXIV_COOKIE")
        self.client = aiohttp.ClientSession(cookies={'PHPSESSID': cookie},headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0", "Referer": "https://www.pixiv.net/"})
        #name = os.getenv("TWITTER_NAME")
        #email = os.getenv("TWITTER_EMAIL")
        #pw = os.getenv("TWITTER_PW")
        #self.twitterClient = Client('en-US')
        #await self.twitterClient.login(auth_info_1=name,auth_info_2=email,password=pw,cookies_file="twt_cookies.json")
        # load webhook mappings (maps channel name -> [ENV_VAR_NAMES])
        self.webhooks = json.load(open("./configs/webhooks.json", "r"))
        # load optional character mapping (danbooru-tag -> canonical thread name)
        char_map_path = "./configs/char_map.json"
        if os.path.exists(char_map_path):
            try:
                self.char_map = json.load(open(char_map_path, "r"))
            except Exception:
                self.char_map = {}
        else:
            self.char_map = {}
        series_map_path = "./configs/series_map.json"
        if os.path.exists(series_map_path):
            try:
                self.series_map = json.load(open(series_map_path, "r"))
            except Exception:
                self.series_map = {}
        else:
            self.series_map = {}
        safety_map_path = "./configs/safety_map.json"
        if os.path.exists(safety_map_path):
            try:
                self.safety_map = json.load(open(safety_map_path, "r"))
            except Exception:
                self.safety_map = {}
        else:
            self.safety_map = {}
        await self._load_extensions()
        if not self.synced:
            
            self.synced = not self.synced
            self.logger.info("Synced command tree")

    async def close(self) -> None:
        await super().close()
        await self.client.close()

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
    bot = CustomBot(prefix="!", ext_dir="cogs")
    bot.run()


if __name__ == "__main__":
    main()