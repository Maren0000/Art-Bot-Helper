from __future__ import annotations
import io
import os
from discord.ext import commands
import discord
import datetime
import exception
import json
from utils import bluesky_get, compute_hashes, detect_platform, imagehash, pixiv_ajax_get
from base64 import b64encode

from view import AutoPostView

class PostingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

        post_data, hq_image, image_name, hashes, embed_fallback, platform = await self.fetch_and_validate_image(
            link, ctx.guild, image_num
        )

        view = AutoPostView(ctx.author, timeout=300)

        # Run ML model for character/series detection (works for all platforms)
        charas_model, series, safety = await self.tags_model_pass(hq_image, image_name)
        view.characters = ",".join(charas_model)
        
        # For Pixiv, also check Pixiv tags for additional character/series info
        if platform == "pixiv":
            charas_pixiv, series_pixiv = self.tags_pixiv_pass(post_data)
            view.characters = ",".join(charas_model | charas_pixiv)
            if series_pixiv:
                series = series_pixiv
        
        # Finding forum channel based on detected series and safety
        if series != "" and safety != "":
            for channel in ctx.guild.channels:
                if channel.name == series + "-" + safety:
                    view.selected_forum = channel
                    break

        embed = discord.Embed(
            title="User Confirmation",
            description="Are you sure you want to confirm the following options?",
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.now()
        )

        chara_desc = view.characters if view.characters != "" else "Please enter a character name."
        forum_desc = view.selected_forum.mention if view.selected_forum else "Please select a forum channel."
        embed.add_field(name="Detected Characters", value=chara_desc, inline=False)
        embed.add_field(name="Detected Channel", value=forum_desc, inline=False)

        view.message = await ctx.send(embed=embed, view=view)
        await view.wait()

        if view.confirmed:
            threads, _, _ = await self.find_character_threads(view.selected_forum, view.characters)
            img = hq_image.read()
            thread_links = await self.create_embed_and_send(
                link, post_data, threads, ctx, view.selected_forum.name, 
                embed_fallback, img, image_name, hashes, image_num, platform
            )
            
            embed = discord.Embed(
                title="Successfully posted!",
                description="Your art has been posted in " + view.selected_forum.jump_url,
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="Threads & Links", value=thread_links)
            await view.message.edit(embed=embed)
        else:
            embed = discord.Embed(
                title="Autopost Cancelled",
                description="The poster has cancelled the post or it has timed out.",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
            await view.message.edit(embed=embed)

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

        post_data, hq_image, image_name, hashes, embed_fallback, platform = await self.fetch_and_validate_image(
            link, ctx.guild, image_num
        )

        threads, _, _ = await self.find_character_threads(forum_channel, characters.strip())
        
        img = hq_image.read()
        thread_links = await self.create_embed_and_send(
            link, post_data, threads, ctx, forum_channel.name, 
            embed_fallback, img, image_name, hashes, image_num, platform
        )
        
        embed = discord.Embed(
            title="Successfully posted!",
            description="Your art has been posted in " + forum_channel.jump_url,
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Threads & Links", value=thread_links)
        await ctx.send(embed=embed)
        
    @post.error
    @auto_post.error
    async def posting_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now()
        )
        self.bot.logger.error("Posting command error", exc_info=error)
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/post gacha {series} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, exception.InvalidLink):
            embed.description = "Invalid link! Please check {link} argument\nSupported Sites:\n\
                           - Pixiv (<https://www.pixiv.net>)\n- Bluesky (<https://bsky.app>)"
        elif isinstance(error, exception.ForumNotFound):
            embed.description = "Could not find correct forum channel! Check that {series} and {safety_level} is correct."
        elif isinstance(error, exception.AccessDenied):
            embed.description = "You do not have access to the channel you are trying to post to!"
        elif isinstance(error, exception.ThreadsNotFound):
            embed.description = "Could not find all character threads!\nMissing threads:\n" + str(error).lstrip("Command raised an exception: str: ")
        elif isinstance(error, exception.NotPoster):
            embed.description = "You aren't allowed to post art!"
        elif isinstance(error, exception.RequestFailed):
            embed.description = "The bot has failed to contact an external server. Please try again or ping Maren about this issue."
        elif isinstance(error, exception.AIImageFound):
            embed.description = "The artist has labeled that this image has been AI assisted. As such, it cannot be added to this server."
        elif isinstance(error, exception.CharacterDetectFail):
            embed.description = "The automatic character detector has failed. Please use resubmit the link with the character list."
        elif isinstance(error, exception.DuplicateImageFound):
            embed.description = "This image has already been posted to this server!\n" + str(error).lstrip("Command raised an exception: str: ")
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)
        
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

    async def tags_model_pass(self, hq_image: io.BytesIO, image_name: str) -> tuple[set, str, str]:
        """
        Run ML model on image to detect characters, series, and safety rating.
        
        Args:
            hq_image: BytesIO of the high-quality image
            image_name: Filename to determine image format
            
        Returns:
            tuple: (characters_set, series_str, safety_str)
        """
        # Reset stream position and read image bytes
        hq_image.seek(0)
        image = hq_image.read()
        hq_image.seek(0)  # Reset for later use
        
        # Determine format from filename
        if ".png" in image_name.lower():
            mime = "image/png"
        elif ".webp" in image_name.lower():
            mime = "image/webp"
        elif ".gif" in image_name.lower():
            mime = "image/gif"
        else:
            mime = "image/jpeg"
        
        gradioIn = f"data:{mime};base64,{b64encode(image).decode('utf-8')}"

        image_input = {
            "url": gradioIn,
            "is_stream": False
        }

        result = self.bot.gradio_client.predict(
        image_path=image_input,
        artist_threshold=0.5,
        character_threshold=0.85,
        copyright_threshold=0.5,
        general_threshold=0.5,
        meta_threshold=0.5,
        rating_threshold=0.5,
        year_threshold=0.5,
        api_name="/_wrap_predict"
        )

        charas = set()
        for chara in result[1]:
            if chara in self.bot.config.char_map:
                charas.add(self.bot.config.char_map[chara])

        series = ""
        for series_can in result[2]:
            if series_can in self.bot.config.series_map:
                series = self.bot.config.series_map[series_can]
                break
        
        safety = ""
        if len(result[5]) != 0:
            safety = self.bot.config.safety_map[next(iter(result[5]))] 
        
        return charas, series, safety

    def tags_pixiv_pass(self, ajax_resp: dict) -> str | str:
        chara_tags = set()
        series = ""
        for tag_dict in ajax_resp['body']['tags']['tags']:
            tag = tag_dict['tag']
            if tag in self.bot.config.char_map:
                chara_tags.add(self.bot.config.char_map[tag])
            elif tag in self.bot.config.series_map:
                series = self.bot.config.series_map[tag]
        
        return chara_tags, series

    async def store_image_hash(self, hashes: dict, link: str, platform: str, guild_id: int, thread_id: int, message_id: int) -> None:
        """Store image hashes in database for duplicate detection."""
        await self.bot.db.add_image(
            phash=hashes["phash"],
            dhash=hashes["dhash"],
            source_url=link,
            source_platform=platform,
            guild_id=guild_id,
            thread_id=thread_id,
            message_id=message_id,
        )

    async def create_embed_and_send(self, link: str, post_data: dict, threads: list, context: commands.Context, channel_name, embed_fallback: bool, hq_image: bytes, image_name: str, hashes: dict, image_num: int | None = None, platform: str = "pixiv") -> str:
        msg = ""
        
        # Build embed based on platform
        if platform == "pixiv":
            embed_title = post_data['body']["title"]
            embed_url = post_data['body']["extraData"]["meta"]["canonical"]
            embed_author_name = "@" + post_data['body']['userName']
            embed_author_url = "https://www.pixiv.net/users/" + post_data['body']["userId"]
            fallback_link = link.replace("pixiv", "phixiv")
        elif platform == "bluesky":
            embed_title = post_data.get("title", "Bluesky Post")
            embed_url = post_data.get("url", link)
            embed_author_name = "@" + post_data.get("author_handle", "unknown")
            embed_author_url = post_data.get("author_url", link)
            fallback_link = link  # No phixiv equivalent for Bluesky
        else:
            embed_title = "Art Post"
            embed_url = link
            embed_author_name = "Unknown"
            embed_author_url = link
            fallback_link = link

        if not embed_fallback:
            embed = discord.Embed(
            title=embed_title,
            url=embed_url,
            color=discord.Color.purple(),
            timestamp=datetime.datetime.now()
            )
            embed.set_author(name=embed_author_name, url=embed_author_url)
            embed.add_field(name="Original Poster", value=context.author.name, inline=False)
            embed.set_image(url="attachment://"+image_name)
            embed.set_footer(text="Maren's Art Bot Services")
        else:
            if image_num and platform == "pixiv":
                embed = "Poster: "+ context.author.name + "\n" + fallback_link + "/" + str(image_num)
            else:
                embed = "Poster: "+ context.author.name + "\n" + fallback_link

        first_post = None
        for thread in threads:
            if not embed_fallback:
                post = await thread.send(content=f"<{link}>",embed=embed, file=discord.File(io.BytesIO(hq_image),filename=image_name))
            else:
                post = await thread.send(content=embed)
            
            # Store first post for hash tracking
            if first_post is None:
                first_post = post
            
            if thread == threads[len(threads)-1]:
                msg += "- " + post.jump_url
            else:
                msg += "- " + post.jump_url + "\n"

        # Store image hash in database after successful posting
        if first_post is not None:
            await self.store_image_hash(
                hashes=hashes,
                link=link,
                platform=platform,
                guild_id=context.guild.id,
                thread_id=first_post.channel.id,
                message_id=first_post.id,
            )

        await self.send_webhook(embed, post, channel_name, link)

        if embed_fallback:
            if platform == "pixiv":
                msg += "\n**NOTE:** Older embed system (Phixiv) has been used due to the image being too big to upload directly."
            else:
                msg += "\n**NOTE:** Image was too large to upload directly. Linked version shown instead."
        return msg
    
    async def send_webhook(self, embed, post: discord.Message, channel_name: str, link: str):
        if channel_name in self.bot.config.webhooks:
            embed.set_image(url=post.embeds[0].image.url)
            for webhook_env in self.bot.config.webhooks[channel_name]:
                await self.bot.client.post(os.getenv(webhook_env), data ={"payload_json":  json.dumps({"content": f"<{link}>", "embeds": [embed.to_dict()]})})
    
    async def check_duplicate(self, image: io.BytesIO, guild_id: int) -> tuple[dict, list]:
        """
        Check if image is a duplicate and return hashes.
        Returns (hashes_dict, list_of_similar_images).
        Raises DuplicateImageFound if duplicate exists in the same guild.
        """
        # Reset stream position for reading
        image.seek(0)
        hashes = compute_hashes(image)
        image.seek(0)  # Reset for later use
        
        # Convert ImageHash objects to hex strings for storage/comparison
        hash_strings = {
            "phash": str(hashes["phash"]),
            "dhash": str(hashes["dhash"]),
        }
        
        # Find similar images in database
        similar = await self.bot.db.find_similar(hash_strings["phash"])
        
        # Filter to same guild and check if truly similar using phash + dhash
        duplicates = []
        for img in similar:
            if img.guild_id == guild_id:
                # Double-check with dhash for accuracy
                stored_phash = imagehash.hex_to_hash(img.phash)
                stored_dhash = imagehash.hex_to_hash(img.dhash)
                
                phash_similar = (hashes["phash"] - stored_phash) <= 8
                dhash_similar = (hashes["dhash"] - stored_dhash) <= 10
                
                if phash_similar and dhash_similar:
                    duplicates.append(img)
        
        return hash_strings, duplicates

    async def fetch_and_validate_image(self, link: str, guild: discord.Guild, image_num: int | None = None) -> tuple[dict, io.BytesIO, str, dict, bool, str]:
        """
        Validate link, fetch image from supported platform, check for duplicates, and determine fallback mode.
        
        Returns:
            tuple: (post_data, hq_image, image_name, hashes, embed_fallback, platform)
        
        Raises:
            InvalidLink: If link is not from a supported platform
            DuplicateImageFound: If image was already posted to this guild
        """
        platform = detect_platform(link)
        embed_fallback = False
        
        if platform == "pixiv":
            post_data, hq_image, image_name = await pixiv_ajax_get(self.bot, link, image_num)
        elif platform == "bluesky":
            post_data, hq_image, image_name = await bluesky_get(
                self.bot,
                link, 
                image_num,
            )
        else:
            raise exception.InvalidLink("Invalid Link! Supported platforms: Pixiv, Bluesky")

        # Check for duplicates before proceeding
        hashes, duplicates = await self.check_duplicate(hq_image, guild.id)
        if duplicates:
            dup = duplicates[0]
            raise exception.DuplicateImageFound(
                f"Post: https://discord.com/channels/{dup.guild_id}/{dup.thread_id}/{dup.message_id}"
            )

        # Determine if we need embed fallback based on server boost level
        max_size = 52428799 if guild.premium_tier > 1 else 10485759
        if hq_image.getbuffer().nbytes > max_size:
            embed_fallback = True

        return post_data, hq_image, image_name, hashes, embed_fallback, platform

    async def find_character_threads(self, forum_channel: discord.ForumChannel, characters: str) -> tuple[list, list, list]:
        """
        Find all character threads, group threads, and "All Characters" thread in forum.
        
        Args:
            forum_channel: The forum channel to search
            characters: Comma-separated character names
            
        Returns:
            tuple: (threads, thread_names, group_names)
            
        Raises:
            ThreadsNotFound: If any required threads are missing
        """
        charas = characters.lower().replace("_", " ").split(",")
        charas = [chara.strip() for chara in charas]
        
        threads = []
        thread_names = []
        group_names = []
        
        # Helper to process a thread
        def process_thread(thread):
            if thread.name == "All Characters" and "All Characters" not in thread_names:
                threads.append(thread)
                thread_names.append("All Characters")

            if thread.name.lower() in charas and thread.name.lower() not in thread_names:
                threads.append(thread)
                thread_names.append(thread.name.lower())
                if (len(thread.applied_tags) != 0 and 
                    thread.applied_tags[0].name != "Indie" and 
                    thread.applied_tags[0].name.lower() + " (group)" not in group_names):
                    group_names.append(thread.applied_tags[0].name.lower() + " (group)")
        
        # Search active threads
        for thread in forum_channel.threads:
            process_thread(thread)
            if len(threads) == len(charas) + 1:
                break
        
        # Search archived threads if needed
        if len(threads) != len(charas) + 1:
            async for thread in forum_channel.archived_threads():
                process_thread(thread)
                if len(threads) == len(charas) + 1:
                    break
        
        # Find group threads
        if group_names:
            for group_name in group_names:
                for thread in forum_channel.threads:
                    if group_name == thread.name.lower() and thread.name.lower() not in thread_names:
                        threads.append(thread)
                        thread_names.append(thread.name.lower())
                        break
                if group_name not in thread_names:
                    async for thread in forum_channel.archived_threads():
                        if group_name == thread.name.lower() and thread.name.lower() not in thread_names:
                            threads.append(thread)
                            thread_names.append(thread.name.lower())
                            break

        # Check for missing threads
        if len(threads) != len(charas) + len(group_names) + 1:
            missing = []
            if "All Characters" not in thread_names:
                missing.append("All Characters")
            for chara_name in charas:
                if chara_name not in thread_names:
                    missing.append(chara_name)
            for group_name in group_names:
                if group_name not in thread_names:
                    missing.append(group_name)
            raise exception.ThreadsNotFound("\n".join(f"- {name}" for name in missing))
        
        return threads, thread_names, group_names

async def setup(bot):
    await bot.add_cog(PostingCog(bot))
