from discord.ext import commands
import discord
import json

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
        if json_file.filename.endswith(".json"):
            json_data = await json_file.read()
            self.bot.char_map = json.loads(json_data)
            open("./configs/char_map.json", "wb").write(json_data)

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
        if json_file.filename.endswith(".json"):
            json_data = await json_file.read()
            self.bot.series_map = json.loads(json_data)
            open("./configs/series_map.json", "wb").write(json_data)

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
        if json_file.filename.endswith(".json"):
            json_data = await json_file.read()
            self.bot.webhooks = json.loads(json_data)
            open("./configs/webhooks.json", "wb").write(json_data)

async def setup(bot):
    await bot.add_cog(UpdateCog(bot))