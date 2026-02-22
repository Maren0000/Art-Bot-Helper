import asyncio
import logging
import os
from base64 import b64encode

from discord.ext import commands, tasks

from utils.tag_extract import run_update


class Tasks(commands.Cog):
    """Periodically pings the Gradio server to prevent it from sleeping."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.gradio_keepalive.start()
        self.char_map_refresh.start()

    def cog_unload(self) -> None:
        self.gradio_keepalive.cancel()
        self.char_map_refresh.cancel()

    @tasks.loop(hours=23)
    async def gradio_keepalive(self) -> None:
        """Send a tiny image to the Gradio model to keep the space awake."""
        await self._send_task_update("Gradio keepalive task started.")
        try:
            # 1x1 red PNG (smallest valid PNG possible)
            pixel = self._create_1x1_png()
            gradio_in = f"data:image/png;base64,{b64encode(pixel).decode('utf-8')}"

            image_input = {
                "url": gradio_in,
                "is_stream": False,
            }

            self.bot.gradio_client.predict(
                image_path=image_input,
                artist_threshold=0.5,
                character_threshold=0.85,
                copyright_threshold=0.5,
                general_threshold=0.5,
                meta_threshold=0.5,
                rating_threshold=0.5,
                year_threshold=0.5,
                api_name="/_wrap_predict",
            )
            self.logger.info("Gradio keepalive ping sent successfully.")
            await self._send_task_update("Gradio keepalive task finished successfully.")
        except Exception as e:
            self.logger.error(f"Gradio keepalive ping failed: {e}")
            await self._send_task_update(f"Gradio keepalive task failed: {e}")

    @gradio_keepalive.before_loop
    async def before_gradio_keepalive(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24*10)
    async def char_map_refresh(self) -> None:
        """Rebuild the character map from Danbooru data on a schedule."""
        await self._send_task_update("Character map refresh task started.")
        try:
            total = await asyncio.to_thread(run_update, self.bot.config)
            if hasattr(self.bot, "config"):
                self.bot.config.reload_char_map()
            self.logger.info(f"Character map refresh completed with {total} entries.")
            await self._send_task_update(
                f"Character map refresh task finished successfully with {total} entries."
            )
        except Exception as e:
            self.logger.error(f"Character map refresh failed: {e}")
            await self._send_task_update(f"Character map refresh task failed: {e}")

    @char_map_refresh.before_loop
    async def before_char_map_refresh(self) -> None:
        await self.bot.wait_until_ready()

    @staticmethod
    def _create_1x1_png() -> bytes:
        """Return the raw bytes of a minimal 1×1 red PNG image."""
        import struct
        import zlib

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        # Single pixel: filter byte (0) + RGB (255, 0, 0)
        raw_data = zlib.compress(b"\x00\xff\x00\x00")
        idat = _chunk(b"IDAT", raw_data)
        iend = _chunk(b"IEND", b"")
        return signature + ihdr + idat + iend

    async def _send_task_update(self, message: str) -> None:
        channel_id = os.getenv("TASK_STATUS_CHANNEL_ID")
        if not channel_id:
            return
        try:
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                channel = await self.bot.fetch_channel(int(channel_id))
            await channel.send(message)
        except Exception as e:
            self.logger.error(f"Failed to send task update message: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tasks(bot))
