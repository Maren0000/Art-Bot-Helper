from __future__ import annotations
from discord.ext import commands
import discord
import datetime

from services.posting import (
    create_embed_and_send,
    error_description as _error_description,
    fetch_and_validate_image,
    find_character_threads,
    find_forum_by_name,
    tags_model_pass,
    tags_pixiv_pass,
)
from view import AutoPostView


def _build_error_embed(error: Exception, command) -> discord.Embed:
    description, python_error = _error_description(error)
    embed = discord.Embed(
        title=f"Error in command {command}!",
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
    )
    if python_error is not None:
        embed.add_field(name="Python error", value=python_error)
    return embed


def _status_embed(step: str, command_name: str) -> discord.Embed:
    return discord.Embed(
        title=f"Processing /{command_name}…",
        description=step,
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(),
    )


async def _start_status_message(ctx: commands.Context, initial_step: str) -> discord.Message:
    """Establish a single message we can edit for the whole command lifecycle.

    For slash invocations: overwrites the deferred 'Bot is thinking…' placeholder.
    For prefix invocations: sends a fresh message we can edit later.
    """
    command_name = ctx.command.qualified_name if ctx.command else "command"
    embed = _status_embed(initial_step, command_name)
    if ctx.interaction is not None:
        if ctx.interaction.response.is_done():
            await ctx.interaction.edit_original_response(embed=embed)
        else:
            await ctx.interaction.response.send_message(embed=embed)
        return await ctx.interaction.original_response()
    return await ctx.send(embed=embed)


def _make_status_updater(message: discord.Message, command_name: str):
    """Return an async callable(step_text) that edits the status message."""
    async def update(step: str) -> None:
        try:
            await message.edit(embed=_status_embed(step, command_name))
        except discord.HTTPException:
            # A status-update glitch should never break the command.
            pass
    return update


def _build_confirmation_embed(
    characters: str | None,
    selected_forum: discord.ForumChannel | None,
    last_error: Exception | None,
) -> discord.Embed:
    if last_error is None:
        embed = discord.Embed(
            title="User Confirmation",
            description="Are you sure you want to confirm the following options?",
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.now(),
        )
    else:
        desc, _ = _error_description(last_error)
        embed = discord.Embed(
            title="Posting Failed — Adjust and Retry",
            description=f"**Previous attempt failed:** {desc}\n\nAdjust the fields below and click Retry.",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(),
        )

    chara_desc = characters if characters else "Please enter a character name."
    forum_desc = selected_forum.mention if selected_forum else "Please select a forum channel."
    embed.add_field(name="Characters", value=chara_desc, inline=False)
    embed.add_field(name="Forum", value=forum_desc, inline=False)
    return embed


class PostingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_error(
        self,
        ctx: commands.Context,
        error: Exception,
        *,
        status_message: discord.Message | None = None,
    ) -> None:
        """Render an error embed in the status/deferred message (or send a fresh message if neither exists)."""
        self.bot.logger.error("Posting command error", exc_info=error)
        embed = _build_error_embed(error, ctx.command)
        if status_message is not None:
            try:
                await status_message.edit(embed=embed, view=None, attachments=[])
                return
            except discord.HTTPException:
                pass
        if ctx.interaction is not None and ctx.interaction.response.is_done():
            try:
                await ctx.interaction.edit_original_response(embed=embed, view=None, attachments=[])
                return
            except discord.HTTPException:
                pass
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="autopost")
    async def auto_post(self, ctx: commands.Context, link: str, image_num: int | None = None):
        """
        Post art to one of the art forum channels

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        link: str
            Pixiv or Twitter link to image.
        image_num: str
            Optional argument to select specific image from multiple ones in a post.
        """
        await ctx.defer()
        message = await _start_status_message(ctx, "🔗 Reading link...")
        update = _make_status_updater(message, ctx.command.qualified_name)

        try:
            post_data, hq_image, image_name, hashes, embed_fallback, platform = await fetch_and_validate_image(
                self.bot, link, ctx.guild, image_num, on_status=update,
            )

            # Run ML model for character/series detection (works for all platforms)
            charas_model, series, safety = await tags_model_pass(self.bot, hq_image, image_name, on_status=update)
            characters = ",".join(charas_model)

            # For Pixiv, also check Pixiv tags for additional character/series info
            if platform == "pixiv":
                charas_pixiv, series_pixiv = tags_pixiv_pass(self.bot.config, post_data)
                characters = ",".join(charas_model | charas_pixiv)
                if series_pixiv:
                    series = series_pixiv

            # Finding forum channel based on detected series and safety
            selected_forum = find_forum_by_name(ctx.guild, series, safety)
        except Exception as e:
            return await self._send_error(ctx, e, status_message=message)

        last_error: Exception | None = None

        while True:
            view = AutoPostView(
                ctx.author,
                characters=characters,
                selected_forum=selected_forum,
                retry=last_error is not None,
                timeout=300,
            )
            embed = _build_confirmation_embed(characters, selected_forum, last_error)
            await message.edit(embed=embed, view=view)
            view.message = message

            await view.wait()
            characters = view.characters
            selected_forum = view.selected_forum

            if not view.confirmed:
                cancel_embed = discord.Embed(
                    title="Autopost Cancelled",
                    description="The poster has cancelled the post or it has timed out.",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(),
                )
                await message.edit(embed=cancel_embed, view=None)
                return

            try:
                threads, _, _ = await find_character_threads(selected_forum, characters, on_status=update)
                hq_image.seek(0)
                img = hq_image.read()
                thread_links, post_id = await create_embed_and_send(
                    self.bot, link, post_data, threads, ctx.author.name, ctx.guild.id, selected_forum.name,
                    embed_fallback, img, image_name, hashes, image_num, platform,
                    on_status=update,
                )

                success_embed = discord.Embed(
                    title="Successfully posted!",
                    description=f"Your art has been posted in {selected_forum.jump_url}",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.now(),
                )
                success_embed.add_field(name="Threads & Links", value=thread_links)
                if post_id is not None:
                    success_embed.set_footer(text=f"Post ID: {post_id} — use /deletepost to remove from database")
                await message.edit(embed=success_embed, view=None)
                return
            except Exception as e:
                self.bot.logger.error("Posting command error", exc_info=e)
                last_error = e
                # Loop continues: the next iteration rebuilds the embed with the
                # error notice and re-enables the view with a Retry button.

    @commands.hybrid_command(name="post")
    async def post(self, ctx: commands.Context, forum_channel: discord.channel.ForumChannel, characters: str, link: str, image_num: int | None = None):
        """
        Post art to one of the art forum channels

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        forum_channel: discord.channel.ForumChannel
            Forum art channel to post in.
        characters: str
            All Characters in the image. Seperated by commas.
        link: str
            Pixiv or Twitter link to image.
        image_num: str
            Optional argument to select specific image from multiple ones in a post.
        """
        await ctx.defer()
        message = await _start_status_message(ctx, "🔗 Reading link...")
        update = _make_status_updater(message, ctx.command.qualified_name)

        try:
            post_data, hq_image, image_name, hashes, embed_fallback, platform = await fetch_and_validate_image(
                self.bot, link, ctx.guild, image_num, on_status=update,
            )

            threads, _, _ = await find_character_threads(forum_channel, characters.strip(), on_status=update)

            img = hq_image.read()
            thread_links, post_id = await create_embed_and_send(
                self.bot, link, post_data, threads, ctx.author.name, ctx.guild.id, forum_channel.name,
                embed_fallback, img, image_name, hashes, image_num, platform,
                on_status=update,
            )
        except Exception as e:
            return await self._send_error(ctx, e, status_message=message)

        embed = discord.Embed(
            title="Successfully posted!",
            description="Your art has been posted in " + forum_channel.jump_url,
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Threads & Links", value=thread_links)
        if post_id is not None:
            embed.set_footer(text=f"Post ID: {post_id} — use /deletepost to remove from database")
        await message.edit(embed=embed)

    @post.error
    @auto_post.error
    async def posting_error(self, ctx: commands.Context, error: commands.CommandError):
        await self._send_error(ctx, error)

    @commands.hybrid_command(name="help")
    async def help(self, ctx: commands.Context):
        """
        Information about how to use the Bot's post commands.
        """
        embed=discord.Embed(title="How to post using the bot",
                            description=("This bot supports using the newer slash commands (/post)."),
                            color=discord.Color.yellow())
        embed.add_field(name="/post", value=("Command for posting to gacha channels (and vocaloid)"
                        "\nSyntax: `/post {forum_channel} {characters} {link} {image_num}`"
                        "\n`{forum_channel}`: Pick from the available list."
                        "\n`{characters}`: Check \"{characters}\" section."
                        "\n`{Link}`: Check \"{Link}\" section."
                        "\n`{image_num}`: Check \"{image_num}\" section."), inline=False)
        embed.add_field(name="{characters}", value=("List of characters in the image. Case-insensitive."
                        "\nTo include multiple characters, write each name split by commas (Ex: `noa,yuuka`)."
                        "\nYou don't need to worry about spaces in the character name if you are using slash commands."), inline=False)
        embed.add_field(name="{Link}", value=("Both Twitter and Pixiv links are supported. Be sure to use the ORIGINAL links when posting. Do not edit the domain."
                        "\nThe bot will download and upload the selected image as a new embed if allowed by the server upload limit. Otherwise, an external embed service (like Phixiv) will be used."), inline=False)
        embed.add_field(name="{image_num}", value=("This is an optional argument. Use it for when a post has multiple images and you want to select a specific one."
                        "\nMust be a number (Ex. 2 for 2nd image in the post)."), inline=False)
        embed.add_field(name="Note on Tags", value=("Please note that if a character thread has a tag, the default behaviour is to find a group thread for that tag."
                        "\nIf that causes issues with posting, please ping Maren about it."), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="deletepost")
    async def delete_post(self, ctx: commands.Context, post_id: int):
        """
        Remove a post entry from the database by its ID.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        post_id: int
            The database ID of the post to delete (shown in the footer of the success embed when posting).
        """
        await ctx.defer()
        deleted = await self.bot.db.delete_image(post_id)
        if deleted:
            embed = discord.Embed(
                title="Post Deleted",
                description=f"Post ID **{post_id}** has been removed from the database.",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
        else:
            embed = discord.Embed(
                title="Post Not Found",
                description=f"No post with ID **{post_id}** exists in the database.",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
        await ctx.send(embed=embed)

    @delete_post.error
    async def delete_post_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
            title="Error in command deletepost!",
            description="Unknown error occurred while using the command",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Please provide a post ID. Usage: `/deletepost {post_id}`"
        elif isinstance(error, commands.BadArgument):
            embed.description = "Post ID must be a number."
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(PostingCog(bot))
