from __future__ import annotations
import io
import os
from discord.ext import commands
import discord
import datetime
import exception
import json
import utils
from base64 import b64encode

import typing

from view import AutoPostView, ForumSelect, BaseModal

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

        if not link.startswith("https://www.pixiv.net"):
            raise exception.InvalidLink("Invalid Link!")

        ajax_resp = await utils.pixiv_ajax_get(self.bot.client, link)

        view = AutoPostView(ctx.author, timeout=300)

        view.characters, series, safety = await self.detect_characters(ajax_resp, image_num)

        # Finding forum channel
        if series != "" and safety != "":
            for channel in ctx.guild.channels:
                if channel.name == series+"-"+safety:
                    view.selected_forum = channel
                    break

        embed = discord.Embed(
        title=f"User Confirmation",
        description="Are you sure you want to confirm the following options?",
        color=discord.Color.yellow(),
        timestamp=datetime.datetime.now()
        )

        chara_desc = view.characters if view.characters != "" else "Please enter a character name."
        forum_desc = view.selected_forum.mention if view.selected_forum else "Please select a forum channel."
        embed.add_field(name="Detected Characters", value=chara_desc, inline=False)
        embed.add_field(name="Detected Channel", value=forum_desc, inline=False)

        view.message = await ctx.send(embed=embed, view=view)
        # wait for the view to stop
        await view.wait()

        if view.confirmed:            
            # Finding Character threads
            charas = view.characters.lower().replace("_", " ").split(",")
            charas = [chara.strip() for chara in charas]
            threads = []
            thread_names = []
            group_names = []
            for thread in view.selected_forum.threads:
                if thread.name == "All Characters":
                    threads.append(thread)
                    thread_names.append("All Characters")

                if thread.name.lower() in charas:
                    threads.append(thread)
                    thread_names.append(thread.name.lower())
                    if len(thread.applied_tags) != 0 and thread.applied_tags[0].name != "Indie" and thread.applied_tags[0].name.lower() + " (group)" not in group_names:
                        group_names.append(thread.applied_tags[0].name.lower() + " (group)")

                if len(threads) == len(charas)+1:
                    break  
            if len(threads) != len(charas)+1:
                async for thread in view.selected_forum.archived_threads():
                    if thread.name == "All Characters":
                        threads.append(thread)
                        thread_names.append("All Characters")

                    if thread.name.lower() in charas:
                        threads.append(thread)
                        thread_names.append(thread.name.lower())
                        if len(thread.applied_tags) != 0 and thread.applied_tags[0].name != "Indie" and thread.applied_tags[0].name.lower() + " (group)" not in group_names:
                            group_names.append(thread.applied_tags[0].name.lower() + " (group)")

                    if len(threads) == len(charas)+1:
                        break
            
            if len(group_names) > 0:
                for group_name in group_names:
                    for thread in view.selected_forum.threads:
                        if group_name == thread.name.lower():
                            threads.append(thread)
                            thread_names.append(thread.name.lower())

            if len(threads) != len(charas)+len(group_names)+1:
                missing_threads = ""
                if "All Characters" not in thread_names:
                    missing_threads += "- All Characters\n"
                for chara_name in charas:
                    if chara_name not in thread_names:
                        missing_threads += "- "+chara_name+"\n"
                for group_name in group_names:
                    if group_name not in thread_names:
                        missing_threads += "- "+group_name+"\n"
                raise(exception.ThreadsNotFound(missing_threads))
            
            # Check if valid link and replace
            thread_links = await self.link_check_and_send(link, threads, ctx, view.selected_forum.name, image_num)
            
            embed = discord.Embed(
            title=f"Successfully posted!",
            description="Your art has been posted in " + view.selected_forum.jump_url,
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
            )

            embed.add_field(name="Threads & Links", value=thread_links)

            await view.message.edit(embed=embed)
        else:
            embed = discord.Embed(
            title=f"Autopost Cancelled",
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
        # Get rid of whitespace at start and end
        characters = characters.strip()
        
        # Finding Character threads
        charas = characters.lower().replace("_", " ").split(",")
        charas = [chara.strip() for chara in charas]
        threads = []
        thread_names = []
        group_names = []
        for thread in forum_channel.threads:
            if thread.name == "All Characters":
                threads.append(thread)
                thread_names.append("All Characters")

            if thread.name.lower() in charas:
                threads.append(thread)
                thread_names.append(thread.name.lower())
                if len(thread.applied_tags) != 0 and thread.applied_tags[0].name != "Indie" and thread.applied_tags[0].name.lower() + " (group)" not in group_names:
                    group_names.append(thread.applied_tags[0].name.lower() + " (group)")

            if len(threads) == len(charas)+1:
                break  
        if len(threads) != len(charas)+1:
            async for thread in forum_channel.archived_threads():
                if thread.name == "All Characters":
                    threads.append(thread)
                    thread_names.append("All Characters")

                if thread.name.lower() in charas:
                    threads.append(thread)
                    thread_names.append(thread.name.lower())
                    if len(thread.applied_tags) != 0 and thread.applied_tags[0].name != "Indie" and thread.applied_tags[0].name.lower() + " (group)" not in group_names:
                        group_names.append(thread.applied_tags[0].name.lower() + " (group)")

                if len(threads) == len(charas)+1:
                    break
        
        if len(group_names) > 0:
            for group_name in group_names:
                for thread in forum_channel.threads:
                    if group_name == thread.name.lower():
                        threads.append(thread)
                        thread_names.append(thread.name.lower())

        if len(threads) != len(charas)+len(group_names)+1:
            missing_threads = ""
            if "All Characters" not in thread_names:
                missing_threads += "- All Characters\n"
            for chara_name in charas:
                if chara_name not in thread_names:
                    missing_threads += "- "+chara_name+"\n"
            for group_name in group_names:
                if group_name not in thread_names:
                    missing_threads += "- "+group_name+"\n"
            raise(exception.ThreadsNotFound(missing_threads))
        
        # Check if valid link and replace
        thread_links = await self.link_check_and_send(link, threads, ctx, forum_channel.name, image_num)
        
        embed = discord.Embed(
        title=f"Successfully posted!",
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
        print(error)
        print(type(error))
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/post gacha {series} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, exception.InvalidLink):
            embed.description = "Invalid link! Please check {link} argument\nSupported Sites:\n\
                           - Pixiv (<https://www.pixiv.net>) [Autopost]\n- Twitter (<https://twitter.com> or <https://x.com>) [Manual posting only]"
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

    async def detect_characters(self, ajax_resp: dict, image_num: int) -> str | str | str:
        image_link = ajax_resp['body']['urls']['thumb']
        if image_num:
            image_link = image_link.replace("_p0_", f"_p{image_num-1}_")
        image_req = await self.bot.client.get(image_link)
        if image_req.status == 200:
            image = await image_req.read()
        else:
            raise exception.RequestFailed("request to pixiv image failed")
        
        if ".jpg" in image_link:
            gradioIn = f"data:image/jpg;base64,{b64encode(image).decode("utf-8")}"
        elif ".png" in image_link:
            gradioIn = f"data:image/png;base64,{b64encode(image).decode("utf-8")}"

        image_input = {
            "url": gradioIn,
            "is_stream": False
        }

        result = self.bot.gradioClient.predict(
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

        chara_temp = []
        for chara in result[1]:
            if chara in self.bot.char_map and self.bot.char_map[chara] not in chara_temp:
                chara_temp.append(self.bot.char_map[chara])

        series = ""
        for series_can in result[2]:
            if series_can in self.bot.series_map:
                series = self.bot.series_map[series_can]
                break
        
        safety = ""
        if len(result[5]) != 0:
            safety = self.bot.safety_map[next(iter(result[5]))] 
        
        return ",".join(chara_temp), series, safety

    async def link_check_and_send(self, link: str, threads: list, context: commands.Context, channel_name, image_num: int | None = None) -> str:
        msg = ""
        phixiv_fallback = False
        if link.startswith("https://www.pixiv.net"):
            ajax_resp = await utils.pixiv_ajax_get(self.bot.client, link)
            if ajax_resp['body']["illustType"] != 2:
                image_link = ajax_resp['body']['urls']['original']
                temp = ajax_resp['body']['urls']['original'].split("/")
                image_name = temp[len(temp)-1]
                if image_num:
                    extension = image_link[-4:]
                    image_link = image_link[:len(image_link)-5]
                    image_link += str(image_num-1)+extension
                image_req = await self.bot.client.get(image_link)
                if image_req.status == 200:
                    if context.guild.premium_tier > 1: # Tier 2 servers get 50MB upload. Non-boosted servers only get 10MB upload
                        if int(image_req.headers['Content-Length']) > 52428799: 
                            phixiv_fallback = True
                        else:
                            image = await image_req.read()
                    else:
                        if int(image_req.headers['Content-Length']) > 10485759: 
                            phixiv_fallback = True
                        else:
                            image = await image_req.read()
                else:
                    raise exception.RequestFailed("request to pixiv image failed")
            else: # Ugoria video
                image, image_name = await utils.ugoria_merge(self.bot.client, id)
                if context.guild.premium_tier > 1:
                    if len(image) > 52428799: 
                        phixiv_fallback = True
                else:
                    if len(image) > 10485759:
                        phixiv_fallback = True

            embed_title = ajax_resp['body']["title"]
            embed_url = ajax_resp['body']["extraData"]["meta"]["canonical"]
            embed_author_name = "@"+ ajax_resp['body']['userName']
            embed_author_url = "https://www.pixiv.net/users/" + ajax_resp['body']["userId"]

        elif link.startswith("https://twitter.com") or link.startswith("https://x.com"):
            temp = link.split("/")
            id = temp[len(temp)-1].split("?", 1)[0]
            id = temp[len(temp)-1].split("#", 1)[0]
            tweet = await self.bot.twitterClient.get_tweet_by_id(id)
            image_link = tweet.media[0].media_url
            if image_num:
                image_link = tweet.media[image_num-1].media_url
            image_req = await self.bot.client.get(image_link)
            temp = tweet.media[0].media_url.split("/")
            image_name = temp[len(temp)-1]
            if image_req.status == 200:
                image = await image_req.read()
                embed_title = "Tweet"
                embed_url = link
                embed_author_name = tweet.user.name
                embed_author_url = "https://twitter.com/" +tweet.user.screen_name
            else:
                raise exception.RequestFailed("request to twitter image failed")
        if not phixiv_fallback:
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
            if image_num:
                embed = "Poster: "+ context.author.name + "\n" + link.replace("pixiv", "phixiv") + "/" + str(image_num)
            else:
                embed = "Poster: "+ context.author.name + "\n" + link.replace("pixiv", "phixiv")

        for thread in threads:
            if not phixiv_fallback:
                post = await thread.send(embed=embed, file=discord.File(io.BytesIO(image),filename=image_name))
            else:
                post = await thread.send(content=embed)
            if thread == threads[len(threads)-1]:
                msg += "- " + post.jump_url
            else:
                msg += "- " + post.jump_url + "\n"

        await self.send_webhook(embed, post, channel_name)

        if phixiv_fallback:
            msg += "\n**NOTE:** Older embed system (Phixiv) has been used due to the image being too big to upload directly."
        return msg
    
    async def send_webhook(self, embed, post: discord.Message, channel_name: str):
        if channel_name in self.bot.webhooks:
            embed.set_image(url=post.embeds[0].image.url)
            for webhook_env in self.bot.webhooks[channel_name]:
                await self.bot.client.post(os.getenv(webhook_env), data ={"payload_json":  json.dumps({"embeds": [embed.to_dict()]})})


async def setup(bot):
    await bot.add_cog(PostingCog(bot))
