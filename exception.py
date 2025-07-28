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

class RequestFailed(commands.CommandInvokeError):
    """A request to an external site has failed."""
    pass

class AIImageFound(commands.CommandInvokeError):
    """User tried to post GenAI image."""
    pass