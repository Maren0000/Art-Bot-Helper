from discord.ext import commands
import discord
import datetime
from cogs.exception import ForumNotFound, ThreadsNotFound, AccessDenied, InvalidLink, NotPoster
import enum

class series(str, enum.Enum):
    GenshinImpact = "genshin"
    HonkaiStarRail = "hsr"
    HonkaiImpact3rd = "hi3"
    ZenlessZoneZero = "zzz"
    BlueArchive = "ba"
    Arknights = "ark"
    AzurLane = "azur"
    NIKKE = "nikke"
    WutheringWaves = "wuwa"
    Snowbreak = "sb"
    UmaMusume = "uma"
    ProjectSekai = "pjsk"
    Vocaloid = "voca"
    testing_only = "test-forum"

class safety_level(str, enum.Enum):
    Art = "art"
    Sus = "sus"
    SC = "sc"

class group(str, enum.Enum):
    Hololive = "hololive"
    Independent = "indie"
    

class PostingCog(commands.Cog):
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
    async def gacha(self, ctx: commands.Context, series: series, safety_level: safety_level, characters: str, link: str):
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
        role_check = ctx.author.get_role(1393719753264201802)
        if not role_check:
            raise(NotPoster("not a poster"))
        
        # Finding forum channel
        for channel in ctx.guild.channels:
            if channel.name == series.value+"-"+safety_level.value:
                forum_channel = channel
                break
        if not forum_channel:
            raise(ForumNotFound("forum not found"))
            
        
        # Verifying if poster has access to channel
        if ctx.author not in forum_channel.members:
            raise(AccessDenied("access denied"))
        
        # Finding Character threads
        
        charas = characters.lower().split(",")
        threads = []
        for thread in forum_channel.threads:
            if thread.name == "All Characters":
                threads.append(thread)

            if thread.name.lower().replace(" ", "_") in charas:
                threads.append(thread)

            if len(threads) == len(charas)+1:
                break
        
        if len(threads) != len(charas)+1:
            raise(ThreadsNotFound("threads not found"))
        
        # Check if valid link and replace
        link = link_check_and_convert(link)

        msg = "Successfully posted in " + forum_channel.name + " and following threads:\n"
        msg += await send_link_to_threads(ctx, threads, link)
        
        await ctx.send(msg)
    
    @gacha.error
    async def posting_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
        )
        print(error)
        print(type(error))
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `!post gacha {series} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, InvalidLink):
            embed.description = "Invalid link! Please check {link} argument\nSupported Sites:\n\
                           - Pixiv (<https://www.pixiv.net>)\n- Twitter (<https://twitter.com> or <https://x.com>)"
        elif isinstance(error, ForumNotFound):
            embed.description = "Could not find correct forum channel! Check that {series} and {safety_level} is correct."
        elif isinstance(error, AccessDenied):
            embed.description = "You do not have access to the channel you are trying to post to!"
        elif isinstance(error, ThreadsNotFound):
            embed.description = "Could not find all character threads! Check that {characters} is correct or if all the threads exist."
        elif isinstance(error, NotPoster):
            embed.description = "You aren't allowed to post art!"
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)
    
    @post.command()
    async def vtub(self, ctx: commands.Context, group: group, safety_level: safety_level, characters: str, link: str):
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
        role_check = ctx.author.get_role(1393719753264201802)
        if not role_check:
            raise(NotPoster("not a poster"))
        
        for channel in ctx.guild.channels:
            if channel.name == "vtub"+"-"+safety_level.value:
                forum_channel = channel
        if not forum_channel:
            raise(ForumNotFound("forum not found"))
        
        # Verifying if poster has access to channel
        if ctx.author not in forum_channel.members:
            raise(AccessDenied("access denied"))
            
        charas = characters.lower().split(",")
        threads = []
        for thread in forum_channel.threads:
            if thread.name == "All Characters":
                threads.append(thread)

            if thread.name.lower() == group.value.lower()+" (group)":
                threads.append(thread)

            if thread.name.lower().replace(" ", "_") in charas:
                threads.append(thread)
        
        if len(threads) != len(charas)+2:
            raise(ThreadsNotFound("threads not found"))
        
        # Check if valid link and replace
        link = link_check_and_convert(link)
        
        msg = "Successfully posted in " + forum_channel.name + " and following threads:\n"
        msg += await send_link_to_threads(ctx, threads, link)
        
        await ctx.send(msg)

    @vtub.error
    async def vtub_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
        )
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `!post vtub {group} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect Argument! Check if the {group} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, InvalidLink):
            embed.description = "Invalid link! Please check {link} argument\nSupported Sites:\n\
                           - Pixiv (<https://www.pixiv.net>)\n- Twitter (<https://twitter.com> or <https://x.com>)"
        elif isinstance(error, ForumNotFound):
            embed.description = "Could not find correct forum channel! Check that {group} and {safety_level} is correct."
        elif isinstance(error, AccessDenied):
            embed.description = "You do not have access to the channel you are trying to post to!"
        elif isinstance(error, ThreadsNotFound):
            embed.description = "Could not find all group/character threads! Check that {group} and {chara1} parameters are correct or if all the threads exist."
        elif isinstance(error, NotPoster):
            embed.description = "You aren't allowed to post art!"
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)
        
    @post.command()
    async def help(self, ctx: commands.Context):
        """
        Information about how to use the Bot's help commands.
        """
        embed=discord.Embed(title="How to post using the bot",
                            description=("This bot supports using both classic prefix commands (!post) and the newer slash commands (/post)."
                                "\nIt's recommened to use the slash commands system since it supports autofill for some sections, while prefix requries manual typing for all arguments."),
                            color=discord.Color.yellow())
        embed.add_field(name="/post gacha", value=("Command for posting to gacha channels (and vocaloid)"
                        "\nSyntax: `/post gacha {series} {safety_level} {characters} {link}`"
                        "\n`{series}` and `{safety_level}`: Pick from the available list."
                        "\n`{characters}`: Check \"{characters}\" section."
                        "\n`{Link}`: Check \"{Link}\" section."), inline=False)
        embed.add_field(name="/post vtub", value=("Command for posting to vtuber channels"
                        "\nSyntax: `/post vtub {group} {safety_level} {characters} {link}`"
                        "\n`{group}` and `{safety_level}`: Pick from the available list."
                        "\n`{characters}`: Check \"{characters}\" section."
                        "\n`{Link}`: Check \"{Link}\" section."), inline=False)
        embed.add_field(name="{characters}", value=("List of characters in the image. Case-insensitive."
                        "\nTo include multiple characters, write each name split by commas (Ex: `noa,yuuka`)."
                        "\nIf the character thread has a space in it, be sure to replace with an underscore (Ex: `rice_shower`)"), inline=False)
        embed.add_field(name="{Link}", value=("Both Twitter and Pixiv links are supported. Be sure to use the ORIGINAL links when posting. Do not edit the domain."
                        "\nFor Pixiv links, the bot will automatically use `phixiv` for embeds. If the post has multiple images, you can select a different image by adding `/{number}` at the end. (Ex: `https://www.pixiv.net/en/artworks/83319118/2` for 2nd image)"
                        "\nFor Twitter links, the bot will automatically use `fxtwitter` for embeds."), inline=False)
        embed.add_field(name="Using prefix versions of the commands", value=("Very similar to the slash command versions. The only difference is that {series}/{group} and {safety_level} will need to be filled in manually."
                        "\nUse the channel name as a guide for both"
                        "\nExample: `!post gacha genshin art keqing,ganyu {link}`"), inline=False)
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

def link_check_and_convert(link: str) -> str:
    if not link.startswith("https://www.pixiv.net") and not link.startswith("https://twitter.com") and not link.startswith("https://x.com"):
        raise InvalidLink("Invalid Link!")
    if link.startswith("https://www.pixiv.net"):
        link = link.replace("pixiv", "phixiv")
    if link.startswith("https://twitter.com"):
        link = link.replace("twitter", "fxtwitter")
    if link.startswith("https://x.com"):
        link = link.replace("x", "fxtwitter")
    return link

async def send_link_to_threads(ctx: commands.Context, threads: list, link: str) -> str:
    msg = ""
    for thread in threads:
        if thread == threads[len(threads)-1]:
            msg += thread.name
        else:
            msg += thread.name + " - "
        await thread.send("Poster: "+ ctx.author.name + "\n" + link)

    return msg

async def setup(bot):
    await bot.add_cog(PostingCog(bot))
