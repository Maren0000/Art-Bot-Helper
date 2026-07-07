import datetime

import discord
from discord.ext import commands

from utils.api_token import SETUP_TOKEN_TTL, mint_setup_token


class TokenCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="token")
    @commands.guild_only()
    async def token(self, ctx: commands.Context):
        """
        Get a personal access token for the Art Bot userscript.
        """
        # Ephemeral so the token request never shows up in a public channel.
        await ctx.defer(ephemeral=True)

        role_id = self.bot.config.poster_role_id
        if role_id is None:
            await ctx.send(
                embed=discord.Embed(
                    title="Userscript API not configured",
                    description="No poster role is set. Ask an admin to set `poster_role_id` in the web panel (API Settings).",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        if role_id not in [role.id for role in ctx.author.roles]:
            await ctx.send(
                embed=discord.Embed(
                    title="Not allowed",
                    description="You aren't allowed to post art! (Missing the poster role.)",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        expiry_days = self.bot.config.token_expiry_days
        token = mint_setup_token(ctx.author.id, ctx.guild.id)
        setup_deadline = datetime.datetime.now() + datetime.timedelta(seconds=SETUP_TOKEN_TTL)

        if expiry_days:
            expires = datetime.datetime.now() + datetime.timedelta(days=expiry_days)
            expiry_text = f"Once linked, the link expires <t:{int(expires.timestamp())}:D> — rerun /token to re-link."
        else:
            expiry_text = "Once linked, the userscript stays linked — no need to rerun /token."

        dm_embed = discord.Embed(
            title="Your Art Bot setup token",
            description=(
                f"```\n{token}\n```\n"
                f"This setup token is **single-use** and expires <t:{int(setup_deadline.timestamp())}:R>.\n"
                f"{expiry_text}\n\n"
                "**Setup:** open the Art Bot panel on Twitter/X or Pixiv, open its settings (⚙), "
                "paste this token into the *Setup token* field, and hit **Link account**.\n\n"
                "Keep this token private — anyone who uses it can post as you."
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(),
        )

        try:
            await ctx.author.send(embed=dm_embed)
        except discord.Forbidden:
            await ctx.send(
                embed=discord.Embed(
                    title="Couldn't DM you",
                    description="Enable DMs from server members and rerun /token.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        await ctx.send(
            embed=discord.Embed(
                title="Token sent!",
                description=f"Check your DMs. {expiry_text}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(TokenCog(bot))
