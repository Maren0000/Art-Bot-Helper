import asyncio

from discord.ext import commands
import discord
import json

from utils.tag_extract import run_update

class UpdateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="update")
    @commands.guild_only()
    @commands.is_owner()
    async def update(self, ctx: commands.Context):
        """
        Base command for updating config files. Displays available subcommands.
        Please only use these if you know what you are doing.
        """
        #print(ctx.invoked_subcommand)
        if ctx.invoked_subcommand is None:
           await ctx.send("Avaliable groups: characters - series")
    
    @update.command()
    @commands.guild_only()
    @commands.is_owner()
    async def characters(self, ctx: commands.Context, json_file: discord.Attachment):
        """
        Update the character mapping JSON file.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        json_file: discord.Attachment
            JSON file to update character list.
        """
        if not json_file.filename.endswith(".json"):
            await ctx.send("❌ Invalid file type. Please upload a `.json` file.")
            return
        try:
            json_data = await json_file.read()
            self.bot.char_map = json.loads(json_data)
            open("./configs/char_map.json", "wb").write(json_data)
            await ctx.send("✅ Character map updated successfully.")
        except Exception as e:
            await ctx.send(f"❌ Failed to update character map: {e}")

    @update.command()
    @commands.guild_only()
    @commands.is_owner()
    async def series(self, ctx: commands.Context, json_file: discord.Attachment):
        """
        Update the series mapping JSON file.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        json_file: discord.Attachment
            JSON file to update character list.
        """
        if not json_file.filename.endswith(".json"):
            await ctx.send("❌ Invalid file type. Please upload a `.json` file.")
            return
        try:
            json_data = await json_file.read()
            self.bot.series_map = json.loads(json_data)
            open("./configs/series_map.json", "wb").write(json_data)
            await ctx.send("✅ Series map updated successfully.")
        except Exception as e:
            await ctx.send(f"❌ Failed to update series map: {e}")

    @update.command()
    @commands.guild_only()
    @commands.is_owner()
    async def webhooks(self, ctx: commands.Context, json_file: discord.Attachment):
        """
        Update the webhooks JSON file.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        json_file: discord.Attachment
            JSON file to update character list.
        """
        if not json_file.filename.endswith(".json"):
            await ctx.send("Invalid file type. Please upload a `.json` file.")
            return
        try:
            json_data = await json_file.read()
            self.bot.webhooks = json.loads(json_data)
            open("./configs/webhooks.json", "wb").write(json_data)
            await ctx.send("Webhooks updated successfully.")
        except Exception as e:
            await ctx.send(f"Failed to update webhooks: {e}")

    @update.command(name="char_map_refresh")
    @commands.guild_only()
    @commands.is_owner()
    async def char_map_refresh(self, ctx: commands.Context):
        """
        Force refresh the character map using Danbooru data.
        """
        await ctx.defer()
        try:
            total = await asyncio.to_thread(run_update, self.bot.config)
            self.bot.config.reload_char_map()
            await ctx.send(f"Character map refresh completed with {total} entries.")
        except Exception as e:
            await ctx.send(f"Character map refresh failed: {e}")

async def setup(bot):
    await bot.add_cog(UpdateCog(bot))