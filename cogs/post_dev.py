import io
from discord.ext import commands
import discord
import datetime
import exception
import enum
import json
import zipfile
from PIL import Image

class series(str, enum.Enum):
    testingonly = "test-forum"
    donotuse = "fake"

class safety_level(str, enum.Enum):
    Art = "art"
    Sus = "sus"
    SC = "sc"

class group(str, enum.Enum):
    Hololive = "hololive"
    Independent = "indie"
    

class PostingDevCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @commands.hybrid_group(name="post")
    async def post(self, ctx: commands.Context):
        """
        Base command for posting. Displays available subcommands.
        """
        #print(ctx.invoked_subcommand)
        if ctx.invoked_subcommand is None:
           await ctx.send("Avaliable groups: gacha - vtub - anime")
    
    @post.command()
    async def gacha(self, ctx: commands.Context, series: series, safety_level: safety_level, characters: str, link: str, image_num: int | None = None):
        """
        Post art to one of the gacha game forums (or vocaloid forums)

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        series: series
            Series that the character is from.
        safety_level: safety_level
            "Safety Level" based on the art piece.
        characters: str
            All Characters in the image. Seperated by commas.
        link: str
            Pixiv or Twitter link to image.
        """
        await ctx.defer()
        # Get rid of whitespace at start and end
        characters = characters.strip()

        role_check = ctx.author.get_role(1393719753264201802)
        if not role_check:
            raise(exception.NotPoster("not a poster"))
        
        # Finding forum channel
        for channel in ctx.guild.channels:
            if channel.name == series.value+"-"+safety_level.value:
                forum_channel = channel
                break
        if not forum_channel:
            raise(exception.ForumNotFound("forum not found"))
            
        
        # Verifying if poster has access to channel
        if ctx.author not in forum_channel.members:
            raise(exception.AccessDenied("access denied"))
        
        # Finding Character threads
        charas = characters.lower().replace("_", " ").split(",")
        charas = [chara.strip() for chara in charas]
        threads = []
        thread_names = []
        for thread in forum_channel.threads:
            if thread.name == "All Characters":
                threads.append(thread)
                thread_names.append("All Characters")

            if thread.name.lower() in charas:
                threads.append(thread)
                thread_names.append(thread.name.lower())

            if len(threads) == len(charas)+1:
                break
        for thread in await forum_channel.archived_threads():
            if thread.name == "All Characters":
                threads.append(thread)
                thread_names.append("All Characters")

            if thread.name.lower() in charas:
                threads.append(thread)
                thread_names.append(thread.name.lower())

            if len(threads) == len(charas)+1:
                break
        
        if len(threads) != len(charas)+1:
            missing_threads = ""
            if "All Characters" not in thread_names:
                missing_threads += "- All Characters\n"
            for chara_name in charas:
                if chara_name not in thread_names:
                    missing_threads += "- "+chara_name+"\n"
            raise(exception.ThreadsNotFound(missing_threads))
        
        # Check if valid link and replace
        thread_links = await self.link_check_and_send(link, threads, ctx.author, image_num)
        
        embed = discord.Embed(
        title=f"Successfully posted!",
        description="Your art has been posted in " + forum_channel.jump_url,
        color=discord.Color.green(),
        timestamp=datetime.datetime.now()
        )

        embed.add_field(name="Threads & Links", value=thread_links)

        await ctx.send(embed=embed)
    
    @gacha.error
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
                           - Pixiv (<https://www.pixiv.net>)\n- Twitter (<https://twitter.com> or <https://x.com>)"
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
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)
    
    @post.command()
    async def vtub(self, ctx: commands.Context, group: group, safety_level: safety_level, characters: str, link: str, image_num: int | None = None):
        """
        Post art to the V-Tuber forums.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        group: group
            Group that the V-Tuber is from.
        safety_level: safety_level
            "Safety Level" based on the art piece.
        characters: str
            All Characters in the image. Seperated by commas.
        link: str
            Pixiv or Twitter link to image.
        """
        await ctx.defer()
        # Get rid of whitespace at start and end
        characters = characters.strip()

        role_check = ctx.author.get_role(1393719753264201802)
        if not role_check:
            raise(exception.NotPoster("not a poster"))
        
        for channel in ctx.guild.channels:
            if channel.name == "test-forum"+"-"+safety_level.value:
                forum_channel = channel
        if not forum_channel:
            raise(exception.ForumNotFound("forum not found"))
        
        # Verifying if poster has access to channel
        if ctx.author not in forum_channel.members:
            raise(exception.AccessDenied("access denied"))
            
        charas = characters.lower().replace("_", " ").split(",")
        charas = [chara.strip() for chara in charas]
        threads = []
        thread_names = []
        for thread in forum_channel.threads:
            if thread.name == "All Characters":
                threads.append(thread)
                thread_names.append("All Characters")

            if group.value != "indie" and thread.name.lower() == group.value.lower().strip()+" (group)":
                threads.append(thread)
                thread_names.append(group.value.lower().strip())

            if thread.name.lower() in charas:
                threads.append(thread)
                thread_names.append(thread.name.lower())
        for thread in await forum_channel.archived_threads():
            if thread.name == "All Characters":
                threads.append(thread)
                thread_names.append("All Characters")

            if group.value != "indie" and thread.name.lower() == group.value.lower().strip()+" (group)":
                threads.append(thread)
                thread_names.append(group.value.lower().strip())

            if thread.name.lower() in charas:
                threads.append(thread)
                thread_names.append(thread.name.lower())

        if group.value != "indie" and len(threads) != len(charas)+2:
            missing_threads = ""
            if "All Characters" not in thread_names:
                missing_threads += "- All Characters\n"
            if group.value.lower() not in thread_names:
                missing_threads += "- "+group.value+"\n"
            for chara_name in charas:
                if chara_name not in thread_names:
                    missing_threads += "- "+chara_name+"\n"
            raise(exception.ThreadsNotFound(missing_threads))
        elif len(threads) != len(charas)+1:
            missing_threads = ""
            if "All Characters" not in thread_names:
                missing_threads += "- All Characters\n"
            for chara_name in charas:
                if chara_name not in thread_names:
                    missing_threads += "- "+chara_name+"\n"
            raise(exception.ThreadsNotFound(missing_threads))
        
        # Check if valid link and replace
        thread_links = await self.link_check_and_send(link, threads, ctx.author, image_num)
        
        embed = discord.Embed(
        title=f"Successfully posted!",
        description="Your art has been posted in " + forum_channel.jump_url,
        color=discord.Color.green(),
        timestamp=datetime.datetime.now()
        )
        
        embed.add_field(name="Threads & Links", value=thread_links)

        await ctx.send(embed=embed)

    @vtub.error
    async def vtub_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now()
        )
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/post vtub {group} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect Argument! Check if the {group} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, exception.InvalidLink):
            embed.description = "Invalid link! Please check {link} argument\nSupported Sites:\n\
                           - Pixiv (<https://www.pixiv.net>)\n- Twitter (<https://twitter.com> or <https://x.com>)"
        elif isinstance(error, exception.ForumNotFound):
            embed.description = "Could not find correct forum channel! Check that {group} and {safety_level} is correct."
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
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)
        
    @post.command()
    async def help(self, ctx: commands.Context):
        """
        Information about how to use the Bot's post commands.
        """
        embed=discord.Embed(title="How to post using the bot",
                            description=("This bot supports using the newer slash commands (/post)."),
                            color=discord.Color.yellow())
        embed.add_field(name="/post gacha", value=("Command for posting to gacha channels (and vocaloid)"
                        "\nSyntax: `/post gacha {series} {safety_level} {characters} {link} {image_num}`"
                        "\n`{series}` and `{safety_level}`: Pick from the available list."
                        "\n`{characters}`: Check \"{characters}\" section."
                        "\n`{Link}`: Check \"{Link}\" section."
                        "\n`{image_num}`: Check \"{image_num}\" section."), inline=False)
        embed.add_field(name="/post vtub", value=("Command for posting to vtuber channels"
                        "\nSyntax: `/post vtub {group} {safety_level} {characters} {link} {image_num}`"
                        "\n`{group}` and `{safety_level}`: Pick from the available list."
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
        await ctx.send(embed=embed)
    
    @post.command()
    async def anime(self, ctx: commands.Context):
        """
        Coming Soon.
        """
        await ctx.send("Maren is still thinking about how to handle the anime channels, so this command isn't avaiable yet")
        '''args = message.split(" ")
        if len(args) != 3:
            await ctx.send("Message format is incorrect! Please format the message as `!post {group} {series} {chara1,chara2} {link}`")
            return
        charas = args[1].lower().split(",")
        for channel in ctx.guild.channels:
            if channel.name == args[0]+"-sus":
                forum_channel = channel
                print(channel.name)
        if not forum_channel:
            await ctx.send("Could not find correct forum channel! Check that {series} is correct")
            return
        
        threads = []
        for thread in forum_channel.threads:
            if thread.name == "All Characters":
                threads.append(thread)

            if thread.name.lower().replace(" ", "_") in charas:
                threads.append(thread)
        
        if len(threads) != len(charas)+1:
            await ctx.send("Could not all character threads! Check that {chara1} is correct or if all the threads exist.")
            return
        
        msg = "Secussfully posted in " + forum_channel.name + " and following threads:\n"
        for thread in threads:
            msg += thread.name + " - "
            await thread.send(args[2].replace("pixiv", "phixiv"))
        
        await ctx.send(msg)'''

    async def link_check_and_send(self, link: str, threads: list, author, image_num: int | None = None) -> str:
        msg = ""
        phixiv_fallback = False
        if not link.startswith("https://www.pixiv.net") and not link.startswith("https://twitter.com") and not link.startswith("https://x.com"):
            raise exception.InvalidLink("Invalid Link!")
        if link.startswith("https://www.pixiv.net"):
            temp = link.split("/")
            id = temp[len(temp)-1].split("?", 1)[0]
            id = temp[len(temp)-1].split("#", 1)[0]
            resp = await self.bot.client.get("https://www.pixiv.net/ajax/illust/"+id)
            if resp.status == 200:
                json_resp = json.loads(await resp.text())
                if json_resp['body']['aiType'] > 1:
                    raise exception.AIImageFound("pixiv ai image")
                if json_resp['body']["illustType"] != 2:
                    image_link = json_resp['body']['urls']['original']
                    temp = json_resp['body']['urls']['original'].split("/")
                    image_name = temp[len(temp)-1]
                    if image_num:
                        extension = image_link[-4:]
                        image_link = image_link[:len(image_link)-5]
                        image_link += str(image_num-1)+extension
                    image_req = await self.bot.client.get(image_link)
                    if image_req.status == 200:
                        if int(image_req.headers['Content-Length']) > 10485759: # Temp because non-boosted servers only get 10MB upload
                            phixiv_fallback = True
                        else:
                            image = await image_req.read()
                    else:
                        raise exception.RequestFailed("request to pixiv image failed")
                else: # Ugoria video
                    ugo_resp = await self.bot.client.get("https://www.pixiv.net/ajax/illust/"+id+"/ugoira_meta")
                    if resp.status == 200:
                        ugo_json_resp = json.loads(await ugo_resp.text())
                        ugo_zip_resp = await self.bot.client.get(ugo_json_resp["body"]["originalSrc"])
                        if ugo_zip_resp.status == 200:
                            frames = {f["file"]: f["delay"] for f in ugo_json_resp["body"]["frames"]}
                            zipcontent = await ugo_zip_resp.read()
                            with zipfile.ZipFile(io.BytesIO(zipcontent)) as zf:
                                files = zf.namelist()
                                images = []
                                durations = []
                                width = 0
                                height = 0
                                for file in files:
                                    f = io.BytesIO(zf.read(file))
                                    im = Image.open(fp=f)
                                    width = max(im.width, width)
                                    height = max(im.height, height)
                                    images.append(im)
                                    durations.append(int(frames[file]))

                                first_im = images.pop(0)
                                image = io.BytesIO()
                                first_im.save(image, format='webp', save_all=True, append_images=images, duration=durations, lossless=True, quality=100)
                                image = image.getvalue()
                                image_name = "ugoria_"+ str(id) + ".webp"
                                if len(image) > 10485759:
                                    phixiv_fallback = True
                        else:
                            raise exception.RequestFailed("request to pixiv ugoria zip failed")
                    else:
                        raise exception.RequestFailed("request to pixiv ugoria api failed")

                embed_title = json_resp['body']["title"]
                embed_url = json_resp['body']["extraData"]["meta"]["canonical"]
                embed_author_name = "@"+ json_resp['body']['userName']
                embed_author_url = "https://www.pixiv.net/users/" + json_resp['body']["userId"]
                                
            else:
                raise exception.RequestFailed("request to pixiv ajax failed")
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
            embed.add_field(name="Original Poster", value=author.name, inline=False)
            embed.set_image(url="attachment://"+image_name)
            embed.set_footer(text="Maren's Art Bot Services")
        else:
            if image_num:
                embed = "Poster: "+ author.name + "\n" + link.replace("pixiv", "phixiv") + "/" + str(image_num)
            else:
                embed = "Poster: "+ author.name + "\n" + link.replace("pixiv", "phixiv")

        for thread in threads:
            if not phixiv_fallback:
                post = await thread.send(embed=embed, file=discord.File(io.BytesIO(image),filename=image_name))
            else:
                post = await thread.send(content=embed)
            if thread == threads[len(threads)-1]:
                msg += "- " + post.jump_url
            else:
                msg += "- " + post.jump_url + "\n"

        if phixiv_fallback:
            msg += "\n**NOTE:** Older embed system (Phixiv) has been used due to the image being too big to upload directly."
        return msg

async def setup(bot):
    await bot.add_cog(PostingDevCog(bot))
