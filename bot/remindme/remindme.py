import asyncio
import concurrent.futures
import datetime
import functools
from typing import Optional
import uuid

import discord
from discord.ext import commands

from bot import constants, singletons
from bot.logger import command_log, log
from bot.persistence import DatabaseConnector
from bot.remindme import parser


class RemindMeCog(commands.Cog):
    def __init__(self, bot):
        """Initializes the Cog.

        .. todo::
            * Pretty Embeds
            * List navigation
                - going from list to single view
                - being able to delete reminders in single view
                - going from single view back to list
                - navigating from view to view
                - timeout after one minute of not using navigation
                - using some kind of cache so as to not spam the DB when
                    browsing the list
            * Support for reacting on users' reminders, adding them to your own
            * Link to original message in reminder
            * Link reminder specification in !remindme help message

        Args:
            bot (discord.ext.commands.Bot): The bot for which this cog should be enabled.
        """
        self.bot = bot
        self._db_connector = DatabaseConnector(
            constants.DB_FILE_PATH, constants.DB_INIT_SCRIPT
        )

        # Static variables which are needed for running jobs created by the scheduler.
        # For the entire explanation see ./SAM/bot/moderation/moderation.ModerationCog
        RemindMeCog.bot = self.bot
        RemindMeCog.db_connector = self._db_connector

        singletons.SCHEDULER.add_job(
            _scheduled_reminder_vacuum,
            replace_existing=True,
            id="reminder_vacuum",
            trigger="cron",
            day_of_week="mon",
            hour="3",
        )

    @commands.group(name="remindme", invoke_without_command=True)
    @command_log
    async def remindme(
        self, ctx: commands.Context, *, reminder_spec: Optional[str] = None
    ):
        """
        The main `remindme` command, which allows users to quickly create
        reminders dynamically according to the reminder specification.

        If no reminder specification is provided, :py:meth:`remindme_help` is
        subsequently called.

        Args:
            ctx (commands.Context): The command's invocation context.
            reminder_spec (Optional[str]): The reminder's specification that
                should be parsed.
        """
        if reminder_spec is None:
            await self.remindme_help(ctx)
            return

        reminder_dt, reminder_msg = await self.parse_reminder(reminder_spec)

        if len(reminder_msg) > 1750:
            await ctx.send(
                "Die Nachricht deiner Erinnerung ist leider zu lang.\n"
                "Bitte stelle sicher, dass sie maximal 1750 Zeichen hat, "
                "damit ich sie dir auch zustellen kann."
            )

        sent_message = await ctx.send(
            "Deine Erinnerung wurde erfolgreich hinzugefügt :calendar_spiral:"
        )

        if ctx.channel is not discord.DMChannel:
            reminder_msg += f"\n\n[Originale Nachricht]({sent_message.jump_url})"

        await self.schedule_reminder(ctx, reminder_dt, reminder_msg)

    @remindme.command(name="help")  # use class HelpCommand (?)
    @command_log
    async def remindme_help(self, ctx: commands.Context):
        await ctx.send(":construction_site: Under construction :construction_site:")

    @remindme.command(name="list", aliases=("ls",))
    @command_log
    async def remindme_list(self, ctx: commands.Context):
        # await ctx.send(":construction_site: Under construction :construction_site:")
        reminder_job_ids = list(self._db_connector.get_reminder_jobs_for_user(ctx.author.id))
        await ctx.send("Jobs:\n" + "\n".join(f"{job_id}" for job_id in reminder_job_ids))
        await ctx.send("Scheduler Jobs:\n" + "\n".join(f"{singletons.SCHEDULER.get_job(str(job_id), 'default')}" for job_id in reminder_job_ids))

    @remindme.command(name="view", aliases=("show",))
    @command_log
    async def remindme_view(self, ctx: commands.Context):
        await ctx.send(":construction_site: Under construction :construction_site:")

    @remindme.command(name="remove", aliases=("rm", "delete"))
    @command_log
    async def remindme_remove(self, ctx: commands.Context):
        await ctx.send(":construction_site: Under construction :construction_site:")

    async def parse_reminder(self, reminder_spec: str) -> tuple[datetime.datetime, str]:
        """
        Launches a new thread in order to parse the reminder's specification,
        running an otherwise blocking call as a coroutine.

        Args:
            reminder_spec (str): The string which should be parsed.

        Returns:
            tuple[datetime.datetime, str]: The reminder's date and message.
                The message may be an empty string if the user did not specify any.

        Raises:
            ReminderParseError: If an error happens during the parsing process.
        """
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result: tuple[datetime.datetime, str] = await loop.run_in_executor(
                executor=executor,
                func=functools.partial(parser.parse, reminder_spec),
            )

        return result

    async def schedule_reminder(
        self,
        ctx: commands.Context,
        reminder_dt: datetime.datetime,
        reminder_msg: str,
    ):
        """
        Launches a new thread that schedules the reminder in the background,
        running an otherwise blocking call as a coroutine.

        Args:
            ctx (commands.Context): The invocation context of the command
                this method was used in.
            reminder_dt (datetime.datetime): The date and time at which the
                reminder should be sent.
            reminder_msg (str): The reminder's message.
        """
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            await loop.run_in_executor(
                executor=executor,
                func=functools.partial(
                    self._schedule_reminder, ctx, reminder_dt, reminder_msg
                ),
            )

    def _schedule_reminder(
        self,
        ctx: commands.Context,
        reminder_dt: datetime.datetime,
        reminder_msg: str,
    ):
        """
        The blocking function that is used in :func:`schedule_reminder`.

        This function was separately added in order to ensure that every
        call happens sequentially instead of running every method individually
        in the *ThreadPoolExecutor*.

        Args:
            ctx (commands.Context): The invocation context of the command
                this method was used in.
            reminder_dt (datetime.datetime): The date and time at which the
                reminder should be sent.
            reminder_msg (str): The reminder's message.
        """
        reminder_uuid = uuid.uuid4()

        self._db_connector.add_reminder_job(reminder_uuid, reminder_dt, reminder_msg)
        self._db_connector.add_reminder_for_user(reminder_uuid, ctx.author.id)

        reminder_embed = discord.Embed(
            title="Erinnerung :calendar_spiral:",
            description=reminder_msg,
            color=constants.EMBED_COLOR_INFO,
        )

        singletons.SCHEDULER.add_job(
            _scheduled_reminder,
            trigger="date",
            run_date=reminder_dt,
            args=[reminder_uuid, reminder_embed],
            id=str(reminder_uuid),
            replace_existing=True,
        )

    @remindme.error
    async def remindme_error(self, ctx: commands.Context, error):
        """
        Error handler for :obj:`parser.ReminderParseError` exceptions.

        Simply notifies the user about their mistake.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
            error (commands.CommandError): The error raised during the execution of the command.
        """
        if isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, parser.ReminderParseError):
                await ctx.send(
                    "**Fehler beim Auslesen der Erinnerung:**"
                    f"\n{str(error.original.args[0])}"
                )

    @commands.Cog.listener(name="on_raw_reaction_add")
    async def reminder_on_reaction_add(self):
        pass

    @commands.Cog.listener(name="on_raw_reaction_remove")
    async def reminder_on_reaction_remove(self):
        pass


async def _scheduled_reminder(reminder_id: uuid.UUID, embed: discord.Embed):
    """
    Schedules a reminder message to be sent to its users.

    Args:
        reminder_id (uuid.UUID): The reminder's UUID.
        reminder_dt (datetime.datetime): The timestamp of the reminder.
        reminder_msg (str): The reminder's message.
    """
    log.info(
        f"[REMINDME] Sending reminder [%s]",
        reminder_id,
    )

    if not any(RemindMeCog.db_connector.get_reminder_jobs([reminder_id])):
        log.warning("[REMINDME] Reminder does not exist in database anymore. Skipping.")
        return

    guild: discord.Guild = RemindMeCog.bot.get_guild(int(constants.SERVER_ID))

    to_remove: list[tuple[uuid.UUID, int]] = []

    messaged_count = 0
    skipped_count = 0

    for user_id in RemindMeCog.db_connector.get_users_for_reminder_job(reminder_id):
        user: discord.User = guild.get_member(user_id)
        if user:
            try:
                await user.send(embed=embed)
            except Exception as e:
                skipped_count += 1
                log.exception(
                    "[REMINDME] Encountered an unexpected exception when sending reminder "
                    "to user [%s] [%s]:",
                    user.name,
                    user.id,
                    exc_info=e,
                )
            else:
                messaged_count += 1

        else:
            skipped_count += 1

        to_remove.append((reminder_id, user_id))

    if to_remove:
        RemindMeCog.db_connector.remove_many_reminder_for_user(to_remove)
    RemindMeCog.db_connector.remove_reminder_job(reminder_id)

    log.info("[REMINDME] %s messaged, %s skipped.", messaged_count, skipped_count)


async def _scheduled_reminder_vacuum():
    """
    Vacuums the *RemindmeJobs* and *RemindmeUserReminders* tables as well as
    the scheduler's stored data, ensuring that there are no dangling records
    floating around.
    """
    log.info("[REMINDME] Starting vacuum job.")
    user_reminders = RemindMeCog.db_connector.get_reminders_for_users()
    for reminder_id, user_id in user_reminders:
        if not any(RemindMeCog.db_connector.get_reminder_jobs([reminder_id])):
            log.info(
                "[REMINDME] Vacuuming dangling reminder [%s] for user with ID [%s]",
                reminder_id,
                user_id,
            )
            RemindMeCog.db_connector.remove_reminder_for_user(reminder_id, user_id)

    reminder_jobs = RemindMeCog.db_connector.get_reminder_jobs()
    for reminder_id, reminder_dt, reminder_msg in reminder_jobs:
        if not singletons.SCHEDULER.get_job(str(reminder_id), "default"):
            log.info(
                "[REMINDME] Vacuuming dangling reminder job [%s] without scheduled job",
                reminder_id,
            )
            RemindMeCog.db_connector.remove_reminder_job(reminder_id)

    log.info("[REMINDME] Finished vacuum job.")


def setup(bot):
    bot.add_cog(RemindMeCog(bot))
