import datetime
import discord
from discord.ext import commands
from cogs.post import series, safety_level
from cogs.exception import NotPoster, ForumNotFound, AccessDenied, ThreadsNotFound, TooManyArguments, TooLittleArguments

class ThreadCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="thread")
    async def thread(self, ctx: commands.Context):
        """
        Base command for threads. Displays available subcommands.
        """
        #print(ctx.invoked_subcommand)
        if ctx.invoked_subcommand is None:
           await ctx.send("Avaliable groups: create - edit")

    @thread.command()
    async def create(self, ctx: commands.Context, channel: discord.abc.GuildChannel, name: str, embed_link: str | None = None, image_file: discord.Attachment | None = None):
        """
        Create a thread in one of the Art forum channels.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        channel: discord.abc.GuildChannel
            Channel to create the thread in. Must be a forum channel.
        name: str
            Name of the thread. THIS IS CASE-SENSITIVE FOR THIS COMMAND.
        embed_link: str
            Link of an image to embed in the first post. Use either this or image_file.
        image_file: discord.Attachment
            Image upload to embed in the first post. Use either embed_link or this.
        """
        if not embed_link or image_file:
            raise(TooLittleArguments("embed link and image file are missing"))

        if embed_link and image_file:
            raise(TooManyArguments("embed link and image file both exist"))
        
        role_check = ctx.author.get_role(1393719753264201802)
        if not role_check:
            raise(NotPoster("not a poster"))
            
        if not isinstance(channel, discord.channel.ForumChannel):
            raise(ForumNotFound("not a forum channel"))

        # Verifying if poster has access to channel
        if ctx.author not in channel.members:
            raise(AccessDenied("access denied"))
        if embed_link:
            thread = await channel.create_thread(name=name.replace("_", " "), content=embed_link, auto_archive_duration=10080)
        if image_file:
            thread = await channel.create_thread(name=name.replace("_", " "), content=image_file.url, auto_archive_duration=10080)
            #embed_channel = await ctx.guild.fetch_channel("1392350974852464700")
            #embed_channel.send(image_file.url)
        embed = discord.Embed(
        title=f"Succesfully created {thread.thread.name} in {channel.name}!",
        description=thread.thread.jump_url,
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow()
        )
        await ctx.send(embed=embed)
    
    @create.error
    async def create_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
        )
        print(error)
        print(type(error))
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/thread create {channel} {name} {embed_link} {image_file}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, ForumNotFound):
            embed.description = "The channel you linked to is not a forum channel for art. Please pick another channel."
        elif isinstance(error, AccessDenied):
            embed.description = "You do not have access to the channel you are trying to post to!"
        elif isinstance(error, ThreadsNotFound):
            embed.description = "Could not find all character threads! Check that {characters} is correct or if all the threads exist."
        elif isinstance(error, NotPoster):
            embed.description = "You aren't allowed to post art!"
        elif isinstance(error, TooManyArguments):
            embed.description = "You can't use both an image link and file at the same time! Please use one or the other"
        elif isinstance(error, TooLittleArguments):
            embed.description = "You are missing an embed image! Please add a link to one or upload one."
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)

    @thread.command()
    async def edit(self, ctx: commands.Context, channel: discord.abc.GuildChannel, name: str, embed_link: str | None = None, image_file: discord.Attachment | None = None):
        """
        Create a thread in one of the Art forum channels.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        channel: discord.abc.GuildChannel
            Channel to create the thread in. Must be a forum channel.
        name: str
            Name of the thread. Case-insensitive.
        embed_link: str
            Link of an image to embed in the first post. Use either this or image_file.
        image_file: discord.Attachment
            Image upload to embed in the first post. Use either embed_link or this.
        """
        if not embed_link or image_file:
            raise(TooLittleArguments("embed link and image file are missing"))
        
        if embed_link and image_file:
            raise(TooManyArguments("embed link and image file both exist"))
        
        role_check = ctx.author.get_role(1393719753264201802)
        if not role_check:
            raise(NotPoster("not a poster"))
        
        if not isinstance(channel, discord.channel.ForumChannel):
            raise(ForumNotFound("not a forum channel"))
        
        # Verifying if poster has access to channel
        if ctx.author not in channel.members:
            raise(AccessDenied("access denied"))

        for thread in channel.threads:
            if thread.name.lower() == name.lower().replace("_", " "):
                found_thread = thread

        if not found_thread:
            raise(ThreadsNotFound("threads not found"))

        ping_maren = False
        async for message in found_thread.history(limit=1, oldest_first=True):
            if message.author.name == "marengg":
                ping_maren = True
            message = message

        if not ping_maren:
            if embed_link:
                    message = await message.edit(content=embed_link)
            if image_file:
                async for message in thread.history(limit=1, oldest_first=True):
                    message = await message.edit(content=image_file.url)

        if ping_maren:
            maren = await ctx.guild.fetch_member(299194409780641802)
            embed = discord.Embed(
            title=f"Well this is embarrassing...",
            description=f"It seems that my owner had created {message.jump_url} first. They will edit the post when they have the time to do so.\nIf you have used an image attachment, please upload it so my owner can use a link.",
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.utcnow()
            )
            await ctx.send(content=maren.mention, embed=embed)
        else:
            embed = discord.Embed(
            title=f"Succesfully edited {found_thread.name} in {channel.name}!",
            description=f"Link to first message: {message.jump_url}.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
            )
            await ctx.send(embed=embed)

    @edit.error
    async def edit_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
        )
        print(error)
        print(type(error))
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/edit thread {series} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, ForumNotFound):
            embed.description = "The channel you linked to is not a forum channel for art. Please pick another channel."
        elif isinstance(error, AccessDenied):
            embed.description = "You do not have access to the channel you are trying to post to!"
        elif isinstance(error, ThreadsNotFound):
            embed.description = "Could not find all character threads! Check that {characters} is correct or if all the threads exist."
        elif isinstance(error, NotPoster):
            embed.description = "You aren't allowed to post art!"
        elif isinstance(error, TooManyArguments):
            embed.description = "You can't use both an image link and file at the same time! Please use one or the other."
        elif isinstance(error, TooLittleArguments):
            embed.description = "You are missing an embed image! Please add a link to one or upload one."
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)

    @thread.command()
    async def help(self, ctx: commands.Context):
        """
        Information about how to use the Bot's thread commands.
        """
        embed=discord.Embed(title="How to create/edit threads using the bot",
                            description=("This bot supports using the newer slash commands (/thread)."),
                            color=discord.Color.yellow())
        embed.add_field(name="/thread create", value=("Command for create threads in the art forum channels."
                        "\nSyntax: `/thread create {channel} {name} {embed_link} {image_file}`"
                        "\n`{channel}`: Pick from the available list. It must be a forum channel"
                        "\n`{name}`: Name of the new thread. Note that this is **CASE-SENSITIVE** so please try to use the correct official name with proper casing and spaces."
                        "\n`{embed_link}`: URL to an image for the embed preview. Use this or the option below."
                        "\n`{image_file}`: Image attachment for the embed preview. Use this or the option above."), inline=False)
        embed.add_field(name="/thread edit", value=("Command for editing the embed preview on existing threads."
                        "\nSyntax: `/thread edit {channel} {name} {embed_link} {image_file}`"
                        "\nThis is pretty much the exact same syntax as `create` with the only difference being that the name is case-insensitive."), inline=False)
        embed.add_field(name="Thread Image Guidelines", value=("For the main thread images, you usually want to use landscape images more than portrait images as those will look better with Discord's forum previews."
                        "\nWhile both official art and fanart are allowed, generally, it's better to pick official art so that each post has a consistent preview style. A good place to look for such official images are fan wikis."
                        '\nFor "All Characters" threads, try to pick an image that has as many characters from the game as possbile. A good example of this is official wallpaper art. If you can\'t find something like that, then use the game\'s logo.'), inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ThreadCog(bot))