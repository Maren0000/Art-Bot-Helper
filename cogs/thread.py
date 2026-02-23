import datetime
import discord
from discord.ext import commands
from utils import is_emoji
import exception

class ThreadCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def create_thread_in_channel(
        self,
        ctx: commands.Context,
        forum_channel: discord.channel.ForumChannel,
        name: str,
        embed_link: str | None = None,
        image_file: discord.Attachment | None = None,
        tags: str | None = None,
    ) -> discord.Thread:
        name = name.strip()
        normalized_name = name.replace("_", " ")
        normalized_key = normalized_name.casefold()

        if not embed_link and not image_file:
            raise exception.TooLittleArguments("embed link and image file are missing")

        if embed_link and image_file:
            raise exception.TooManyArguments("embed link and image file both exist")

        for thread in forum_channel.threads:
            if thread.name.casefold() == normalized_key:
                raise exception.ThreadAlreadyExists("already exists")
        async for thread in forum_channel.archived_threads():
            if thread.name.casefold() == normalized_key:
                raise exception.ThreadAlreadyExists("already exists")

        if embed_link:
            thread = (
                await forum_channel.create_thread(
                    name=normalized_name, content=embed_link, auto_archive_duration=10080
                )
            ).thread
        else:
            embed_channel = await ctx.guild.fetch_channel("1392350974852464700")
            image = await embed_channel.send(file=(await image_file.to_file()))
            thread = (
                await forum_channel.create_thread(
                    name=normalized_name,
                    content=image.attachments[0].url,
                    auto_archive_duration=10080,
                )
            ).thread

        if tags is not None:
            tags_list = tags.lower().replace("_", " ").split(",")
            tags_list = [tag.strip() for tag in tags_list]
            discord_tags = []
            discord_tag_names = []
            for tag in tags_list:
                for discord_tag in forum_channel.available_tags:
                    if discord_tag.name.lower() == tag:
                        discord_tags.append(discord_tag)
                        discord_tag_names.append(discord_tag.name)

            if len(tags_list) != len(discord_tag_names):
                missing_tags = ""
                for tag in tags_list:
                    if tag not in discord_tag_names:
                        missing_tags += "- " + tag + "\n"
                raise exception.ThreadsNotFound(missing_tags)

            await thread.add_tags(*discord_tags, reason="Thread create command")

        return thread

    @commands.hybrid_group(name="thread")
    async def thread(self, ctx: commands.Context):
        """
        Base command for threads. Displays available subcommands.
        """
        #print(ctx.invoked_subcommand)
        if ctx.invoked_subcommand is None:
           await ctx.send("Avaliable groups: create - edit")

    @thread.group(name="create")
    async def create(self, ctx: commands.Context):
        """
        Subcommand command for thread related creation commands. Displays available subcommands.
        """
        #print(ctx.invoked_subcommand)
        if ctx.invoked_subcommand is None:
           await ctx.send("Avaliable groups: post - tag")

    @create.command()
    async def post(self, ctx: commands.Context, forum_channel: discord.channel.ForumChannel, name: str, embed_link: str | None = None, image_file: discord.Attachment | None = None, tags: str | None = None):
        """
        Create a thread in one of the Art forum channels.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        forum_channel: discord.channel.ForumChannel
            Forum channel to create thread in.
        name: str
            Name of the thread. THIS IS CASE-SENSITIVE FOR THIS COMMAND.
        embed_link: str
            Link of an image to embed in the first post. Use either this or image_file.
        image_file: discord.Attachment
            Image upload to embed in the first post. Use either embed_link or this.
        tags: str
            List of tags to add to the thread. Case-insensitive and comma seperated.
        """
        thread = await self.create_thread_in_channel(
            ctx,
            forum_channel,
            name,
            embed_link=embed_link,
            image_file=image_file,
            tags=tags,
        )

        embed = discord.Embed(
        title=f"Successfully created {thread.name} in {forum_channel.name}!",
        description=thread.jump_url,
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow()
        )
        await ctx.send(embed=embed)

    @create.command(name="postall")
    async def postall(self, ctx: commands.Context, series: str, name: str, embed_link: str | None = None, image_file: discord.Attachment | None = None, tags: str | None = None):
        """
        Create a thread in all safety channels for a series.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        series: str
            Series name used to match forum channels by `{series}-{safety}`.
        name: str
            Name of the thread. THIS IS CASE-SENSITIVE FOR THIS COMMAND.
        embed_link: str
            Link of an image to embed in the first post. Use either this or image_file.
        image_file: discord.Attachment
            Image upload to embed in the first post. Use either embed_link or this.
        tags: str
            List of tags to add to the thread. Case-insensitive and comma seperated.
        """
        series = series.strip()
        safety_levels = set(self.bot.config.safety_map.values())
        target_names = {f"{series}-{safety}" for safety in safety_levels}

        forum_channels = [
            channel
            for channel in ctx.guild.channels
            if isinstance(channel, discord.ForumChannel) and channel.name in target_names
        ]

        if not forum_channels:
            raise exception.ForumNotFound("forum channels not found")

        created = []
        skipped = []
        for forum_channel in forum_channels:
            try:
                thread = await self.create_thread_in_channel(
                    ctx,
                    forum_channel,
                    name,
                    embed_link=embed_link,
                    image_file=image_file,
                    tags=tags,
                )
                created.append(f"{forum_channel.name}: {thread.jump_url}")
            except exception.ThreadAlreadyExists:
                skipped.append(forum_channel.name)

        if not created:
            raise exception.ThreadAlreadyExists("already exists")

        embed = discord.Embed(
            title=f"Successfully created {name} in series {series}",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.add_field(name="Created", value="\n".join(created), inline=False)
        if skipped:
            embed.add_field(name="Skipped", value="\n".join(skipped), inline=False)
        await ctx.send(embed=embed)

    @create.command()
    async def tag(self, ctx: commands.Context, forum_channel: discord.channel.ForumChannel, name: str, emote: str):
        """
        Create a tag in one of the Art forum channels.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        forum_channel: discord.channel.ForumChannel
            Forum channel to create thread in.
        name: str
            Name of the new tag. THIS IS CASE-SENSITIVE FOR THIS COMMAND.
        emote: str
            Emote to use for the new tag.
        """
        name = name.strip()
        emote = emote.strip()
        
        if not is_emoji(emote):
            raise(exception.NotAnEmoji("not a unicode emoji"))

        tag = await forum_channel.create_tag(name=name, emoji=emote)

        embed = discord.Embed(
        title=f"Succesfully created {tag.name} in {forum_channel.name}!",
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow()
        )
        await ctx.send(embed=embed)
    
    # Tag errors fail here for some reason?
    @tag.error
    @post.error
    @postall.error
    async def create_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
        )
        self.bot.logger.error("Thread create command error", exc_info=error)
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/thread create {channel} {name} {embed_link} {image_file}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, exception.ThreadsNotFound):
            embed.description = "Could not find all character threads! Check that {characters} is correct or if all the threads exist."
        elif isinstance(error, exception.ThreadAlreadyExists):
            embed.description = "This thread already exists."
        elif isinstance(error, exception.TooManyArguments):
            embed.description = "You can't use both an image link and file at the same time! Please use one or the other"
        elif isinstance(error, exception.TooLittleArguments):
            embed.description = "You are missing an embed image! Please add a link to one or upload one."
        elif isinstance(error, exception.TagsNotFound):
            embed.description = "Could not find all forum tags!\nMissing tags:\n" + str(error).lstrip("Command raised an exception: str: ")
        elif isinstance(error, exception.NotAnEmoji):
            embed.description = "The character provided in emote parameter is not a valid emote."
        else:
            embed.add_field(name="Python error", value=str(error))
        await ctx.send(embed=embed)

    @thread.group(name="edit")
    async def edit(self, ctx: commands.Context):
        """
        Subcommand for thread editing. Displays available subcommands.
        """
        #print(ctx.invoked_subcommand)
        if ctx.invoked_subcommand is None:
           await ctx.send("Avaliable groups: name - embed - tag")

    @edit.command()
    async def name(self, ctx: commands.Context, forum_channel: discord.channel.ForumChannel, old_name: str, new_name: str):
        """
        Edits the name of a thread in one of the Art forum channels.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        forum_channel: discord.channel.ForumChannel
            Forum channel to create thread in.
        old_name: str
            Name of a thread. Case-insensitive.
        new_name: str
            New name to use for the thread. CASE-SENSITIVE!
        """
        old_name = old_name.strip()

        found_thread = None
        for thread in forum_channel.threads:
            if thread.name.lower() == old_name.lower().replace("_", " "):
                found_thread = thread
                break
        if not found_thread:
            async for thread in forum_channel.archived_threads():
                if thread.name.lower() == old_name.lower().replace("_", " "):
                    found_thread = thread
                    break

        if not found_thread:
            raise(exception.ThreadsNotFound("threads not found"))

        original_name = found_thread.name
        found_thread = await found_thread.edit(archived=False, name=new_name)

        embed = discord.Embed(
        title=f"Succesfully edited {original_name} in {forum_channel.name}!",
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow()
        )
        embed.description=f"Renamed the thread to {found_thread.jump_url}."
        await ctx.send(embed=embed)

    @edit.command()
    async def embed(self, ctx: commands.Context, forum_channel: discord.channel.ForumChannel, name: str, embed_link: str | None = None, image_file: discord.Attachment | None = None):
        """
        Edits a thread's embed image in one of the Art forum channels.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        forum_channel: discord.channel.ForumChannel
            Forum channel to create thread in.
        name: str
            Name of the thread. Case-insensitive.
        embed_link: str
            Link of an image to embed in the first post. Use either this or image_file.
        image_file: discord.Attachment
            Image upload to embed in the first post. Use either embed_link or this.
        """
        name = name.strip()

        if not embed_link and not image_file:
            raise(exception.TooLittleArguments("embed link and image file and new_name are missing"))
        
        if embed_link and image_file:
            raise(exception.TooManyArguments("embed link and image file both exist"))

        found_thread = None
        for thread in forum_channel.threads:
            if thread.name.lower() == name.lower().replace("_", " "):
                found_thread = thread
                break
        if not found_thread:
            async for thread in forum_channel.archived_threads():
                if thread.name.lower() == name.lower().replace("_", " "):
                    found_thread = thread
                    break

        if not found_thread:
            raise(exception.ThreadsNotFound("threads not found"))

        ping_maren = False
        if embed_link or image_file:
            async for message in found_thread.history(limit=1, oldest_first=True):
                if message.author.name == "marengg":
                    ping_maren = True
                message = message
        if not ping_maren:
            if embed_link:
                    message = await message.edit(content=embed_link)
            if image_file:
                    embed_channel = await ctx.guild.fetch_channel("1392350974852464700")
                    image = await embed_channel.send(file=(await image_file.to_file()))
                    message = await message.edit(content=image.attachments[0].url)

        if ping_maren:
            maren = await ctx.guild.fetch_member(299194409780641802)
            embed = discord.Embed(
            title=f"Well this is embarrassing...",
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.utcnow()
            )
            embed.description=f"It seems that my owner had created {message.jump_url} first. They will edit the post when they have the time to do so.\nIf you have used an image attachment, please upload it so my owner can use a link."
            await ctx.send(content=maren.mention, embed=embed)
        else:
            embed = discord.Embed(
            title=f"Successfully edited {thread.name} in {forum_channel.name}!",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
            )
            embed.description=f"Updated embed image. Link to first message: {message.jump_url}."
            await ctx.send(embed=embed)

    @edit.command()
    async def tag(self, ctx: commands.Context, forum_channel: discord.channel.ForumChannel, name: str, tags: str | None = None):
        """
        Adds all tags to a thread.

        Parameters
        ----------
        ctx: commands.Context
            The context of the command invocation
        forum_channel: discord.channel.ForumChannel
            Forum channel to create thread in.
        name: str
            Name of the thread. Case-insensitive.
        tags: str
            List of tags to add to the thread. Case-insensitive and comma seperated.
        """
        name = name.strip()

        found_thread = None
        for thread in forum_channel.threads:
            if thread.name.lower() == name.lower().replace("_", " "):
                found_thread = thread
                break
        if not found_thread:
            async for thread in forum_channel.archived_threads():
                if thread.name.lower() == name.lower().replace("_", " "):
                    found_thread = thread
                    break
        
        discord_tags = []
        if tags != None:
            tags = tags.lower().replace("_", " ").split(",")
            tags = [tag.strip() for tag in tags]
            
            discord_tag_names = []
            for tag in tags:
                for discord_tag in forum_channel.available_tags:
                    if discord_tag.name.lower() == tag:
                        discord_tags.append(discord_tag)
                        discord_tag_names.append(discord_tag.name)

            if len(tags) != len(discord_tag_names):
                missing_tags = ""
                for tag in tags:
                    if tag not in discord_tag_names:
                        missing_tags += "- "+tag+"\n"
                raise(exception.TagsNotFound(missing_tags))

        found_thread = await found_thread.edit(archived=False, applied_tags=discord_tags)

        embed = discord.Embed(
        title=f"Successfully edited {found_thread.name} in {forum_channel.name}!",
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow()
        )
        embed.description=f"Added tags to channel."
        await ctx.send(embed=embed)

    @name.error
    @embed.error
    @tag.error
    async def edit_error(self, ctx: commands.Context, error: commands.CommandError):
        embed = discord.Embed(
        title=f"Error in command {ctx.command}!",
        description="Unknown error occurred while using the command",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
        )
        self.bot.logger.error("Thread edit command error", exc_info=error)
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = "Command format is incorrect! Please format the command as `/edit thread {series} {safety_level} {chara1,chara2} {link}`"
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, commands.BadArgument):
            embed.description = "Incorrect argument! Check if the {series} and {safety_level} are correct."
            embed.add_field(name="Python error", value=str(error))
        elif isinstance(error, exception.ThreadsNotFound):
            embed.description = "Could not find all character threads! Check that {characters} is correct or if all the threads exist."
        elif isinstance(error, exception.TooManyArguments):
            embed.description = "You can't use both an image link and file at the same time! Please use one or the other."
        elif isinstance(error, exception.TooLittleArguments):
            embed.description = "You have not given parameters to edit the thread with! Please either include a new name, or link/file to an image."
        elif isinstance(error, exception.TagsNotFound):
            embed.description = "Could not find all forum tags!\nMissing tags:\n" + str(error).lstrip("Command raised an exception: str: ")
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
        embed.add_field(name="/thread create post", value=("Command for creating threads in the art forum channels."
                        "\nSyntax: `/thread create post {forum_channel} {name} {embed_link} {image_file} {tags}`"
                        "\n`{forum_channel}`: Pick from the available list."
                        "\n`{name}`: Name of the new thread. Note that this is **CASE-SENSITIVE** so please try to use the correct official name with proper casing and spaces."
                        "\n`{embed_link}`: URL to an image for the embed preview. Use this or the option below."
                        "\n`{image_file}`: Image attachment for the embed preview. Use this or the option above."
                        "\n`{tags}`: Tags to add to the new thread. Be sure the tag exists before adding them. You can include multiple tags by using commas."), inline=False)
        embed.add_field(name="/thread create postall", value=("Command for creating the same thread in all safety channels for a series."
                "\nSyntax: `/thread create postall {series} {name} {embed_link} {image_file} {tags}`"
                "\n`{series}`: Series name used to match forum channels by `{series}-{safety}`."
                "\n`{name}`: Name of the new thread. Note that this is **CASE-SENSITIVE** so please try to use the correct official name with proper casing and spaces."
                "\n`{embed_link}`: URL to an image for the embed preview. Use this or the option below."
                "\n`{image_file}`: Image attachment for the embed preview. Use this or the option above."
                "\n`{tags}`: Tags to add to the new thread. Be sure the tag exists before adding them. You can include multiple tags by using commas."), inline=False)
        embed.add_field(name="/thread create tag", value=("Command for creating threads in the art forum channels."
                        "\nSyntax: `/thread create post {forum_channel} {name} {emote}`"
                        "\n`{forum_channel}`: Pick from the available list."
                        "\n`{name}`: Name of the new tag. Note that this is **CASE-SENSITIVE** so please try to use the correct official name with proper casing and spaces."
                        "\n`{emote}`: Emote used for the tag."), inline=False)
        embed.add_field(name="/thread edit name", value=("Command for editing the thread name."
                        "\nSyntax: `/thread edit name {forum_channel} {old_name} {new_name}`"
                        "\n`{forum_channel}`: Pick from the available list."
                        "\n`{old_name}`: Name of the thread to edit. Case-insensitive."
                        "\n**But** {new_name} will be **CASE-SENSITIVE** so please keep that in mind if you are renaming a thread."), inline=False)
        embed.add_field(name="/thread edit embed", value=("Command for editing the thread embed."
                        "\nSyntax: `/thread edit name {forum_channel} {name} {embed_link} {image_file}`"
                        "\n`{forum_channel}`: Pick from the available list."
                        "\n`{name}`: Name of the thread to edit. Case-insensitive."
                        "\n`{embed_link}`: URL to an image for the embed preview. Use this or the option below."
                        "\n`{image_file}`: Image attachment for the embed preview. Use this or the option above."), inline=False)
        embed.add_field(name="/thread edit tag", value=("Command for editing the thread tags."
                        "\nSyntax: `/thread edit name {forum_channel} {name} {tags}`"
                        "\n`{forum_channel}`: Pick from the available list."
                        "\n`{name}`: Name of the thread to edit. Case-insensitive."
                        "\n`{tags}`: Tags to add to the new thread. Be sure the tag exists before adding them. You can include multiple tags by using commas. Keep this empty to remove all tags."), inline=False)
        embed.add_field(name="Thread Image Guidelines", value=("For the main thread images, you usually want to use landscape images more than portrait images as those will look better with Discord's forum previews."
                        "\nWhile both official art and fanart are allowed, generally, it's better to pick official art so that each post has a consistent preview style. A good place to look for such official images are fan wikis."
                        '\nFor "All Characters" threads, try to pick an image that has as many characters from the game as possbile. A good example of this is official wallpaper art. If you can\'t find something like that, then use the game\'s logo.'), inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ThreadCog(bot))