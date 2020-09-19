"""This is the main module of the SAM project."""

import asyncio
import traceback

import discord
from discord.ext import commands
from aiohttp import ClientResponseError

from bot import constants
from bot.logger import log


bot = commands.Bot(command_prefix=constants.BOT_PREFIX)


@bot.event
async def on_ready():
    """Event handler for the Bot entering the ready state."""
    print('- Logged in as: {0.user}'.format(bot))

    print('- Initialising extensions...')
    for extension in constants.INITIAL_EXTNS.values():
        bot.load_extension(extension)

    print("\n\n======== BOT IS UP & RUNNING ========\n\n")


@bot.event
async def on_disconnect():
    """Event handler for when the Bot disconnects from Discord."""
    print('\n- {0.user} has disconnected.'.format(bot))


@bot.event
async def on_command_error(ctx, exception):
    """Event handler for errors in command functions.

        Args:
            ctx (discord.Context): The context of the failing command.
            exception (exception): The exception that was thrown.
    """
    ch_name = 'direct message' if isinstance(ctx.channel, discord.DMChannel) else ctx.channel.name
    log.error(
        "Exception while calling command. Message was: %s by %s in channel %s",
        ctx.message.content,
        ctx.message.author,
        ch_name)

    ex = traceback.format_exception(type(exception), exception, exception.__traceback__)
    log.error(''.join(ex))

    if isinstance(exception, commands.CommandInvokeError) and isinstance(exception.original, asyncio.TimeoutError):
        await ctx.send("Du konntest dich wohl nicht entscheiden. Kein Problem, du kannst es einfach später nochmal "
                       "versuchen. :smile:", delete_after=constants.TIMEOUT_INFORMATION)
    elif isinstance(exception, commands.CommandInvokeError) and \
            isinstance(exception.original, ClientResponseError):
        status_code = exception.original.status
        reason = exception.original.message

        embed = discord.Embed(title="HTTP Error: {0}".format(status_code), description=reason,
                              image=constants.URL_HTTP_CAT + f"/{status_code}.jpg")
        await ctx.channel.send(content="Oh, oh. Anscheinend gibt es momentan ein Verbindungsproblem. :scream_cat:",
                               embed=embed)
    elif isinstance(exception, commands.MissingRequiredArgument):
        await ctx.send_help(ctx.command)


if __name__ == '__main__':
    print("- Contacting Discord servers...")
    bot.run(constants.DISCORD_BOT_TOKEN)
