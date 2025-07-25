import discord
from discord.ext import commands

class InvalidLink(commands.CommandInvokeError):
    """Poster has provided an invalid link to process."""
    pass

class ForumNotFound(commands.CommandInvokeError):
    """Forum channel could not be found."""
    pass

class ThreadsNotFound(commands.CommandInvokeError):
    """Thread channels could not be found."""
    pass

class ThreadAlreadyExists(commands.CommandInvokeError):
    """User has tried to create a thread that already exists."""
    pass

class AccessDenied(commands.CommandInvokeError):
    """User does not have access to the channel."""
    pass

class NotPoster(commands.CommandInvokeError):
    """User does not have the poster role."""
    pass

class TooManyArguments(commands.CommandInvokeError):
    """User has passed in too many arguments into the command."""
    pass

class TooLittleArguments(commands.CommandInvokeError):
    """User has passed in too little arguments into the command."""
    pass

class ExceptionHandler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        #self.bot.tree.on_error = self.on_app_command_error

    '''@commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            print("MissingRequiredArgument")
            await ctx.send("Message format is incorrect! Please format the message as `!post gacha {series} {safety_level} {chara1,chara2} {link}`\n"+"Python error: " + str(error))
            return
        if isinstance(error, InvalidLink):
            print("InvalidLink")
            await ctx.send("Invalid link! Please check {link} argument\nSupported Sites: Pixiv (<https://www.pixiv.net>) and Twitter (<https://twitter.com> or <https://x.com>)")
            return
        if isinstance(error, ForumNotFound):
            print("ForumNotFound")
            await ctx.send("Could not find correct forum channel! Check that {series} and {safety_level} is correct")
            return
        if isinstance(error, AccessDenied):
            print("AccessDenied")
            await ctx.send("You do not have access to the channel you are trying to post to!")
            return
        if isinstance(error, ThreadsNotFound):
            print("ThreadsNotFound")
            await ctx.send("Could not find all character threads! Check that {characters} is correct or if all the threads exist.")
            return
        
    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, commands.MissingRequiredArgument):
            if not interaction.response.is_done():
                await interaction.response.send_message("Custom error caught from slash/hybrid!", ephemeral=True)
            else:
                await interaction.followup.send("Custom error caught from slash/hybrid!", ephemeral=True)
        else:
            raise error'''
        
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExceptionHandler(bot))