import asyncio
import concurrent.futures
import datetime
import functools
import re
from typing import Optional, Union
import uuid

import discord
from discord.ext import commands

from bot import constants, singletons
from bot.logger import command_log, log
from bot.persistence import DatabaseConnector
from bot.remindme import parser
import bot.remindme.constants as rm_const


class RemindMeCog(commands.Cog):
    def __init__(self, bot):
        """Initializes the Cog.

        Todo:
            * Link reminder specification in !remindme help message

        Args:
            bot (discord.ext.commands.Bot):
                The bot for which this cog should be enabled.
        """
        self.bot: commands.Bot = bot
        self._db_connector = DatabaseConnector(
            constants.DB_FILE_PATH, constants.DB_INIT_SCRIPT
        )

        self.guild: discord.Guild = self.bot.get_guild(int(constants.SERVER_ID))
        self.channel_mod_log: discord.TextChannel = self.guild.get_channel(
            int(constants.CHANNEL_ID_MODLOG)
        )

        # Static variables which are needed for running jobs created by the scheduler.
        # For the entire explanation see ./SAM/bot/moderation/moderation.ModerationCog
        RemindMeCog.bot = self.bot
        RemindMeCog.db_connector = self._db_connector
        RemindMeCog.guild = self.guild
        RemindMeCog.channel_mod_log = self.channel_mod_log

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
        """The main command to create reminders.

        Allows users to quickly create reminders dynamically according to the
        reminder specification.

        If no reminder specification is provided, :py:meth:`remindme_help` is
        subsequently called.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            reminder_spec (Optional[str]):
                The reminder's specification that should be parsed.

        """
        if reminder_spec is None:
            await self.remindme_help(ctx)
            return

        if (
            not has_mod_role(ctx.author)
            and self._db_connector.get_reminder_job_count_for_author(ctx.author.id)
            > rm_const.REMINDER_USER_CREATE_LIMIT
        ):
            await ctx.send(
                embed=discord.Embed(
                    description="Du kannst nicht mehr als "
                    f"{rm_const.REMINDER_USER_CREATE_LIMIT} Erinnerungen erstellen.",
                    color=constants.EMBED_COLOR_WARNING,
                ),
            )
            return

        reminder_dt, reminder_msg = await self.parse_reminder(reminder_spec)
        if not reminder_msg:
            await ctx.send(
                embed=discord.Embed(
                    title="Fehler beim Erstellen der Erinnerung",
                    description="Deine Erinnerung muss eine Nachricht beinhalten.",
                    color=constants.EMBED_COLOR_WARNING,
                ),
            )
            return

        embed = self.create_reminder_embed(
            reminder_msg, reminder_dt=reminder_dt, author=ctx.author
        )

        is_public = ctx.channel is not discord.DMChannel
        if is_public:
            embed.set_footer(
                text=f"Klicke auf {rm_const.REMINDER_EMOJI} um diese "
                "Erinnerung ebenfalls zu erhalten.",
            )

        sent_message = await ctx.reply(embed=embed)
        reminder_uuid = uuid.uuid4()

        try:
            self._db_connector.add_reminder_job(
                reminder_uuid,
                reminder_dt,
                reminder_msg,
                sent_message.id,
                ctx.channel.id,
                ctx.author.id,
            )

            self._db_connector.add_reminder_for_user(reminder_uuid, ctx.author.id)

            singletons.SCHEDULER.add_job(
                _scheduled_reminder,
                trigger="date",
                run_date=reminder_dt,
                args=[reminder_uuid],
                id=str(reminder_uuid),
                replace_existing=True,
            )

            log.info(
                "[REMINDME] %s#%s (%s) created a new reminder: [%s] (%s) Message: %s",
                ctx.author.name,
                ctx.author.discriminator,
                ctx.author.id,
                reminder_uuid,
                reminder_dt.strftime(rm_const.REMINDER_DT_FORMAT),
                reminder_msg,
            )

        except Exception:
            await self.handle_reminder_creation_error(ctx, reminder_uuid, sent_message)

        else:
            if is_public:
                await sent_message.add_reaction(rm_const.REMINDER_EMOJI)

    @remindme.command(name="help")  # use class HelpCommand (?)
    @command_log
    async def remindme_help(self, ctx: commands.Context):
        await ctx.send(":construction_site: Under construction :construction_site:")

    @remindme.command(name="system", hidden=True)
    @commands.has_role(int(constants.ROLE_ID_MODERATOR))
    @command_log
    async def remindme_system(
        self,
        ctx: commands.Context,
        title: str,
        reminder_msg: str,
        channel: Optional[discord.TextChannel] = None,
        *,
        reminder_spec: Optional[str] = None,
    ):
        """Create a system reminder.

        This command is essentially the same as the bare ``!remindme``, except
        that it may be used by moderators to post a reminder with a title to a
        specific channel.

        Note:
            The parameter ``reminder_msg`` always replaces the message that is
            parsed from the reminder specification. This makes the command a
            little more intuitive to use.

        System reminders cannot be posted in DM channels.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            title (str):
                The title of the reminder.
            reminder_msg (str):
                The description of the reminder.
            channel (Optional[discord.TextChannel]):
                The channel in which the reminder should be posted.
            reminder_spec (Optional[str]):
                The reminder's specification that should be parsed.

        """

        if reminder_spec is None:
            await ctx.message.delete(delay=60)
            return

        if channel is None:
            channel = ctx.channel

        if not isinstance(channel, discord.TextChannel):
            await ctx.message.delete(delay=60)
            await ctx.send(
                embed=discord.Embed(
                    title="Fehler",
                    description="Eine System-Erinnerung kann nur auf einem Server "
                    "gepostet werden.",
                    colour=constants.EMBED_COLOR_WARNING,
                )
            )
            return

        reminder_dt, _ = await self.parse_reminder(reminder_spec)

        embed = self.create_reminder_embed(
            reminder_msg, reminder_dt=reminder_dt, title=title, author=self.bot.user
        )

        embed.set_footer(
            text=f"Klicke auf {rm_const.REMINDER_EMOJI} um diese "
            "Erinnerung ebenfalls zu erhalten.",
        )

        sent_message = await channel.send(embed=embed)
        reminder_uuid = uuid.uuid4()

        try:
            self._db_connector.add_reminder_job(
                reminder_uuid,
                reminder_dt,
                f"**__{title}__**\n{reminder_msg}",
                sent_message.id,
                sent_message.channel.id,
                self.bot.user.id,
            )

            singletons.SCHEDULER.add_job(
                _scheduled_reminder,
                trigger="date",
                run_date=reminder_dt,
                args=[reminder_uuid],
                id=str(reminder_uuid),
                replace_existing=True,
            )

            log.info(
                "[REMINDME] %s#%s (%s) created a new reminder: [%s] (%s) Message: %s",
                ctx.author.name,
                ctx.author.discriminator,
                ctx.author.id,
                reminder_uuid,
                reminder_dt.strftime(rm_const.REMINDER_DT_FORMAT),
                f"{title}: {reminder_msg}",
            )

        except Exception:
            await self.handle_reminder_creation_error(ctx, reminder_uuid, sent_message)

        else:
            await sent_message.add_reaction(rm_const.REMINDER_EMOJI)

    @remindme.command(name="list", aliases=("ls",))
    @command_log
    async def remindme_list(
        self,
        ctx: commands.Context,
        mod_arg: Optional[Union[discord.Member, int, str]] = None,
    ):
        """List available reminders.

        Moderators are able to see all reminders, including their author and UUID,
        depending on which ``mod_arg`` they provide.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            mod_arg (Optional[Union[discord.Member, int, str]]):
                An argument supplied by a moderator. May be either the @mention
                of a member, the ID of a member, or "all".
        """
        if isinstance(ctx.channel, discord.DMChannel):
            is_moderator = False
        else:
            is_moderator = has_mod_role(ctx.author)

        try:
            reminder_jobs = self.fetch_reminders(ctx, is_moderator, mod_arg)
        except (ValueError, TypeError) as error:
            await ctx.send(
                embed=discord.Embed(
                    title="Fehler",
                    description=f"{error.args[0]}\nMögliche Optionen für Moderatoren:\n"
                    "```\n"
                    "!remindme list all - Zeigt alle Erinnerungen aller Nutzer\n"
                    "!remindme list @<user> - Zeigt alle Erinnerungen eines Nutzers\n"
                    "!remindme list <ID> - Zeigt alle Erinnerungen eines Nutzers anhand dessen ID\n"
                    "```",
                    colour=constants.EMBED_COLOR_WARNING,
                ),
            )
            return

        if not reminder_jobs:
            await self.handle_no_jobs_found(ctx, is_mod=is_moderator)
            return

        # Generate pages
        # Each page is an embed that contains REMINDER_LIST_PAGE_ITEM_COUNT jobs
        # at most.
        embed_title = f"{rm_const.REMINDER_EMOJI} Erinnerungen"
        if is_moderator and mod_arg is not None:
            if isinstance(mod_arg, int):
                user: discord.User = self.guild.get_member(mod_arg)
                if user:
                    embed_title += f" - `{user.name}{user.discriminator} - `{user.id}``"
                else:
                    embed_title += f" - `{mod_arg}`"

            elif isinstance(mod_arg, discord.Member):
                embed_title += (
                    f" - {mod_arg.name}#{mod_arg.discriminator} - `{mod_arg.id}`"
                )

        pages = []
        for page_index in range(
            0, len(reminder_jobs), rm_const.REMINDER_LIST_PAGE_ITEM_COUNT
        ):
            page_embed = discord.Embed(
                title=embed_title,
                colour=constants.EMBED_COLOR_INFO,
            )

            for page_job_index, job_id in enumerate(
                reminder_jobs[
                    page_index : page_index + rm_const.REMINDER_LIST_PAGE_ITEM_COUNT
                ]
            ):
                # Moderators are also able to see the reminder's UUID
                # for easier deletion, as well as who created the reminder
                if is_moderator and mod_arg:
                    member: discord.Member = self.guild.get_member(job_id[5])
                    author = member.mention if member else ""
                else:
                    author = ""

                reminder_dt_str = job_id[1].strftime(
                    rm_const.REMINDER_DT_MESSAGE_FORMAT
                )
                field_name = (
                    f"`{str(job_id[0])}` - {reminder_dt_str}"
                    if is_moderator and mod_arg
                    else f"#{page_index + page_job_index + 1} - {reminder_dt_str}"
                )

                sanitized_message = sanitize_str(job_id[2])
                reminder_message = (
                    sanitized_message
                    if len(sanitized_message) <= 25
                    else f"{sanitized_message[:21]} ..."
                )

                field_value = (
                    reminder_message + f"\n\n**Von:** {author}"
                    if is_moderator and mod_arg
                    else reminder_message
                )

                page_embed.add_field(
                    name=field_name,
                    value=field_value,
                    inline=False,
                )

            pages.append(page_embed)

        # Add page number to each page if there are multiple pages
        # and enable browsing
        if len(pages) > 1:
            for index, page in enumerate(pages, 1):
                page.set_footer(text=f"{rm_const.REMINDER_EMOJI} {index}/{len(pages)}")

            def check(reaction_, user_):
                return user_ == ctx.author and str(reaction_.emoji) in (
                    constants.EMOJI_ARROW_BACKWARD,
                    constants.EMOJI_ARROW_FORWARD,
                )

            current_page = 0
            current_embed = pages[current_page]

            message = await ctx.author.send(embed=current_embed)
            await ctx.message.delete()
            await message.add_reaction(constants.EMOJI_ARROW_BACKWARD)
            await message.add_reaction(constants.EMOJI_ARROW_FORWARD)

            while True:
                try:
                    reaction, user = await self.bot.wait_for(
                        "reaction_add", timeout=60, check=check
                    )

                    if (
                        str(reaction.emoji) == constants.EMOJI_ARROW_FORWARD
                        and current_page < len(pages) - 1
                    ):
                        current_page += 1
                        current_embed = pages[current_page]
                        await message.edit(embed=current_embed)

                    elif (
                        str(reaction.emoji) == constants.EMOJI_ARROW_BACKWARD
                        and current_page > 0
                    ):
                        current_page -= 1
                        current_embed = pages[current_page]
                        await message.edit(embed=current_embed)

                except asyncio.TimeoutError:
                    await message.edit(
                        embed=current_embed.copy().set_footer(
                            text="Diese Nachricht ist nun inaktiv."
                        )
                    )
                    break

        else:
            await ctx.author.send(embed=pages[0])
            await ctx.message.delete()

    @remindme.command(name="view")
    @command_log
    async def remindme_view(self, ctx: commands.Context, id_: Union[int, str]):
        """View a reminder via its list index or UUID.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            id_ (Union[int, str]):
                The index or UUID of the reminder to view.
        """
        try:
            job = await self.fetch_reminder_job_via_id(ctx, id_)

        except ValueError:
            await self.handle_invalid_job_id(ctx, is_mod=has_mod_role(ctx.author))

        else:
            if job is None:
                await self.handle_no_job_with_id_found(
                    ctx, is_mod=has_mod_role(ctx.author)
                )
            else:
                await ctx.author.send(
                    embed=await self.create_reminder_embed_from_job(
                        job, with_dt=True, sanitize=True
                    ),
                )
                await ctx.message.delete()

    @remindme.command(name="remove", aliases=("rm",))
    @command_log
    async def remindme_remove(self, ctx: commands.Context, id_: Union[int, str]):
        """Remove a reminder via its list index or UUID.

        The reminder is only removed for the user that issued the command.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            id_ (Union[int, str]):
                The index or UUID of the reminder to remove.
        """
        try:
            job = await self.fetch_reminder_job_via_id(ctx, id_)

        except ValueError:
            await self.handle_invalid_job_id(ctx, is_mod=has_mod_role(ctx.author))

        else:
            if job is None:
                await self.handle_no_job_with_id_found(
                    ctx, is_mod=has_mod_role(ctx.author)
                )
            else:
                self._db_connector.remove_reminder_for_user(job[0], ctx.author.id)

                log.info(
                    "[REMINDME] %s#%s (%s) removed a reminder from themselves: [%s] (%s) by %s - Message:\n%s",
                    ctx.author.name,
                    ctx.author.discriminator,
                    ctx.author.id,
                    job[0],
                    job[1],
                    job[5],
                    job[2],
                )

                await ctx.send(
                    embed=discord.Embed(
                        description="Die Erinnerung wurde erfolgreich gelöscht.",
                        colour=constants.EMBED_COLOR_INFO,
                    ),
                )

    @remindme.command(name="purge")
    @commands.has_role(int(constants.ROLE_ID_MODERATOR))
    @command_log
    async def remindme_purge(self, ctx: commands.Context, id_: Union[int, str]):
        """Purge a reminder from the database.

        The reminder itself is completely removed from the database and will not
        be received by anyone anymore.

        This command can only be used by moderators.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            id_ (Union[int, str]):
                The index or UUID of the reminder to purge.
        """
        try:
            job = await self.fetch_reminder_job_via_id(ctx, id_)

        except ValueError:
            await self.handle_invalid_job_id(ctx, is_mod=has_mod_role(ctx.author))

        else:
            if job is None:
                await self.handle_no_job_with_id_found(
                    ctx, is_mod=has_mod_role(ctx.author)
                )
            else:
                self._db_connector.remove_reminder_job(job[0])
                self._db_connector.remove_reminder_for_users(job[0])

                log.info(
                    "[REMINDME] %s#%s (%s) purged a reminder from the database: [%s] (%s) by %s - Message:\n%s",
                    ctx.author.name,
                    ctx.author.discriminator,
                    ctx.author.id,
                    job[0],
                    job[1],
                    job[5],
                    job[2],
                )

                await ctx.send(
                    embed=discord.Embed(
                        description=f"Die Erinnerung mit UUID `{job[0]}` wurde "
                        "erfolgreich von der Datenbank enfernt.",
                        color=constants.EMBED_COLOR_MODLOG_PURGE,
                    ),
                )

    async def parse_reminder(self, reminder_spec: str) -> tuple[datetime.datetime, str]:
        """Launches a new thread in order to parse the reminder's specification,
        running an otherwise blocking call as a coroutine.

        Args:
            reminder_spec (str):
                The string which should be parsed.

        Returns:
            tuple[datetime.datetime, str]: The reminder's date and message.
                The message may be an empty string if the user did not specify any.

        Raises:
            parser.ReminderParseError: If an error happens during the parsing process.
        """
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result: tuple[datetime.datetime, str] = await loop.run_in_executor(
                executor=executor,
                func=functools.partial(parser.parse, reminder_spec),
            )

        return result

    @staticmethod
    async def create_reminder_embed_from_job(
        job: tuple,
        title: str = f"Erinnerung {rm_const.REMINDER_EMOJI}",
        *,
        with_dt=False,
        sanitize=False,
    ) -> discord.Embed:
        """Does what it says on the tin.

        Wrapper for :py:meth:`create_reminder_embed`.

        Args:
            job (tuple):
                The reminder job fetched from the database.
            title (str):
                A title for the reminder's embed.
            with_dt (bool):
                Whether to add the reminder's time to the embed or not.
            sanitize (bool):
                Whether to sanitize the reminder's message or not.

        Returns:
            discord.Embed: The reminder's embed.
        """
        reminder_dt = job[1]
        reminder_msg = job[2]

        try:
            channel: discord.TextChannel = RemindMeCog.guild.get_channel(job[4])
            message = await channel.fetch_message(job[3]) if channel else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None

        author = RemindMeCog.guild.get_member(job[5])

        return RemindMeCog.create_reminder_embed(
            reminder_msg,
            reminder_dt=reminder_dt if with_dt else None,
            title=title,
            linked_message=message,
            author=author,
            sanitize=sanitize,
        )

    @staticmethod
    def create_reminder_embed(
        reminder_msg: str,
        *,
        reminder_dt: Optional[datetime.datetime] = None,
        title: str = f"Erinnerung {rm_const.REMINDER_EMOJI}",
        linked_message: Optional[discord.Message] = None,
        author: Optional[discord.User] = None,
        sanitize: bool = False,
    ) -> discord.Embed:
        """Helper method that creates a reminder's embed.

        Args:
            reminder_dt (datetime.datetime):
                The reminder's datetime.
            reminder_msg (str):
                The reminder's message.
            title (str):
                The title to set for the embed.
            linked_message (Optional[discord.Message]):
                Optional discord message that is linked in the reminder's message.
            author (Optional[discord.User]):
                Optional user to display as author in the embed's footer.
            sanitize (bool):
                Whether to sanitize the reminder's message or not. Causes all
                newlines to be replaced with spaces, saving space.

        Returns:
            discord.Embed: The reminder's embed.
        """
        if sanitize:
            reminder_msg = sanitize_str(reminder_msg)

        embed = discord.Embed(
            title=title,
            description=reminder_msg,
            colour=constants.EMBED_COLOR_INFO,
        )

        if reminder_dt is not None:
            embed.add_field(
                name="Wann:",
                value=f"{reminder_dt.strftime(rm_const.REMINDER_DT_MESSAGE_FORMAT)}",
            )
        if linked_message is not None and isinstance(linked_message, discord.Message):
            embed.description += f"\n\n[Originale Nachricht]({linked_message.jump_url})"

        if author is not None and isinstance(author, discord.User):
            embed.add_field(
                name="Erstellt von:",
                value=f"{author.name}#{author.discriminator}",
            )

        return embed

    def fetch_reminders(
        self,
        ctx: commands.Context,
        is_mod: bool = False,
        mod_arg: Optional[Union[discord.Member, int, str]] = None,
    ) -> list[tuple]:
        """Helper method that fetches reminders in a consistent manner.

        Additional options for moderators are available through ``is_mod``
        and ``mod_arg``.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            is_mod (bool):
                Whether a moderator is fetching records or not.
            mod_arg (Optional[Union[discord.Member, int, str]]):
                An argument supplied by a moderator. May be either the @mention
                of a member, the ID of a member, or "all".

        Returns:
            list[tuple]: A list of reminder job records.

        Raises:
            ValueError: If ``mod_arg`` receives an invalid argument.
            TypeError: If ``mod_arg`` is of an unsupported type.
        """
        if is_mod and mod_arg is not None:
            if isinstance(mod_arg, discord.Member):
                reminder_jobs = self._db_connector.get_reminder_jobs_for_user(
                    mod_arg.id
                )

            elif isinstance(mod_arg, int):
                reminder_jobs = self._db_connector.get_reminder_jobs_for_user(mod_arg)

            elif isinstance(mod_arg, str):
                if mod_arg.strip().lower() == "all":
                    reminder_jobs = self._db_connector.get_reminder_jobs()
                else:
                    raise ValueError(f"Ungültige option `{mod_arg = }`")
            else:
                raise TypeError(
                    f"Ungültiger Typ `{type(mod_arg)}` für Argument `{mod_arg = }`"
                )

        else:
            reminder_jobs = self._db_connector.get_reminder_jobs_for_user(ctx.author.id)

        return reminder_jobs

    async def fetch_reminder_job_via_id(
        self, ctx: commands.Context, id_: Union[int, str]
    ) -> Optional[tuple]:
        """Helper method that fetches a reminder job via its list index or UUID.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            id_ (Union[int, str]):
                Either the reminder's list index or UUID.

        Returns:
            Optional[tuple]: The reminder job if found or None.

        Raises:
            ValueError: If ``id_`` is neither ``int`` or ``uuid.UUID``.
        """
        if isinstance(id_, int):
            reminder_jobs = self.fetch_reminders(ctx)
            if not reminder_jobs or not id_ <= len(reminder_jobs):
                return

            return reminder_jobs[id_ - 1]

        elif isinstance(id_, str):
            try:
                id_ = uuid.UUID(id_)
            except Exception:
                raise ValueError("Reminder ID is neither an index or a UUID")

            reminder_jobs = self._db_connector.get_reminder_jobs([id_])
            if not reminder_jobs:
                return

            return reminder_jobs[0]

        else:
            raise ValueError("Reminder ID is neither an index or a UUID")

    async def handle_reminder_creation_error(
        self, ctx: commands.Context, reminder_uuid: uuid.UUID, message: discord.Message
    ):
        """Handles exceptions that may occur when creating a reminder.

        The handler attempts to remove the created reminder immediately from the
        database if possible, while also deleting the reminder job's message and
        posting an error message afterwards.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            reminder_uuid (uuid.UUID):
                The created reminder job's UUID.
            message (discord.Message):
                The message of the reminder job that was sent.
        """
        log.exception(
            "[REMINDME][ERROR] Unexpected exception occurred during creation of a reminder",
        )

        try:
            self._db_connector.remove_reminder_job(reminder_uuid)
        except Exception:
            log.exception(
                "[REMINDME][ERROR] While handling the previous exception, another exception occurred"
            )

        await message.delete()
        await ctx.send(
            embed=discord.Embed(
                title="Fehler",
                description="Beim Erstellen der Erinnerung ist etwas schief gegangen.",
                colour=constants.EMBED_COLOR_WARNING,
            ),
        )

    @staticmethod
    async def handle_no_jobs_found(ctx: commands.Context, *, is_mod: bool = False):
        """Handles cases in which no reminder jobs are found.

        Notifies the user who issued the command and deletes the message of
        their command. Moderators receive additional information.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            is_mod (bool):
                Whether the user that issued the command is a moderator or not.
        """
        description = "Es konnten keine Erinnerungen gefunden werden."

        if is_mod:
            description += f"\n\nAusgeführter Befehl:\n`{ctx.message}`"

        await ctx.author.send(
            embed=discord.Embed(
                description=description,
                color=constants.EMBED_COLOR_INFO,
            ),
        )
        await ctx.message.delete()

    @staticmethod
    async def handle_invalid_job_id(ctx: commands.Context, *, is_mod: bool = False):
        """Handles cases in which an invalid reminder job UUID or index was
        provided.

        Notifies the user who issued the command and deletes the message of
        their command. Moderators receive additional information.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            is_mod (bool):
                Whether the user that issued the command is a moderator or not.
        """
        description = "Ungültige ID."

        if is_mod:
            description += (
                " Die ID muss entweder die UUID der Erinnerung oder der Index "
                "einer deiner eigenen Erinnerungen sein.\n\nAusgeführter Befehl:"
                f"\n`{ctx.message}`"
            )

        await ctx.author.send(
            embed=discord.Embed(
                title="Fehler",
                description=description,
                colour=constants.EMBED_COLOR_WARNING,
            ),
        )
        await ctx.message.delete()

    @staticmethod
    async def handle_no_job_with_id_found(
        ctx: commands.Context, *, is_mod: bool = False
    ):
        """Handles cases in which no reminder job with the given index or UUID
        is found.

        Notifies the user who issued the command and deletes the message of
        their command. Moderators receive additional information.

        Args:
            ctx (commands.Context):
                The command's invocation context.
            is_mod (bool):
                Whether the user that issued the command is a moderator or not.
        """
        description = "Es konnte keine Erinnerung mit dieser ID gefunden werden."

        if is_mod:
            description += f"\n\nAusgeführter Befehl:\n`{ctx.message}`"

        await ctx.author.send(
            embed=discord.Embed(
                title="Fehler",
                description=description,
                colour=constants.EMBED_COLOR_WARNING,
            ),
        )
        await ctx.message.delete()

    @remindme.error
    async def remindme_error(self, ctx: commands.Context, error):
        """Error handler for :obj:`parser.ReminderParseError` exceptions.

        Simply posts an error message.

        Args:
            ctx (commands.Context):
                The context in which the command was invoked.
            error (commands.CommandError):
                The error raised during the execution of the command.
        """
        if isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, parser.ReminderParseError):
                await ctx.message.reply(
                    embed=discord.Embed(
                        title="Fehler beim Auslesen der Erinnerung",
                        description=f"{error.original.args[0]}",
                        color=constants.EMBED_COLOR_WARNING,
                    ),
                )

    @commands.Cog.listener(name="on_raw_reaction_add")
    async def reminder_on_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Listens for reminder emoji reactions, adding a user to a reminder if found.

        Args:
            payload (discord.RawReactionActionEvent):
                The payload emitted when a reaction is added or removed.
        """
        if not payload.emoji or not payload.user_id:
            return

        if (
            payload.emoji.name == rm_const.REMINDER_EMOJI
            and payload.user_id != self.bot.user.id
        ):
            job = self._db_connector.get_reminder_job_from_message_id(
                payload.message_id
            )
            if job:
                log.info(
                    f"[REMINDME] Adding reminder [{job[0]}] for user [{payload.user_id}]"
                )
                # Duplicate user reminders are handled in the query itself
                self._db_connector.add_reminder_for_user(job[0], payload.user_id)


async def _scheduled_reminder(reminder_id: uuid.UUID):
    """Schedules a reminder message to be sent to its users.

    Args:
        reminder_id (uuid.UUID):
            The reminder's UUID.
    """
    log.info(f"[REMINDME] Sending reminder [%s]", reminder_id)

    reminder_jobs = RemindMeCog.db_connector.get_reminder_jobs([reminder_id])
    if not any(reminder_jobs):
        log.warning("[REMINDME] Reminder does not exist in database anymore. Skipping.")
        return

    embed = await RemindMeCog.create_reminder_embed_from_job(
        reminder_jobs[0], with_dt=True
    )
    guild: discord.Guild = RemindMeCog.guild

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
                    "[REMINDME] Encountered an unexpected exception when "
                    "sending reminder to user [%s] [%s]:",
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
    """Housekeeping job for persistent data.

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
    for job in reminder_jobs:
        if not singletons.SCHEDULER.get_job(str(job[0]), "default"):
            log.info(
                "[REMINDME] Vacuuming dangling reminder job [%s] without scheduled job",
                job[0],
            )
            RemindMeCog.db_connector.remove_reminder_job(job[0])

    log.info("[REMINDME] Finished vacuum job.")


# # # Utility Functions
# Some of these functions may be moved to a different location, as they're not
# necessarily bound to this cog.


def has_mod_role(member: discord.Member) -> bool:
    """Checks whether a guild member has the moderator role.

    If the supplied ``member`` is not an instance of ``discord.Member``,
    ``False`` is consequently returned.

    Args:
        member (discord.Member):
            The member to check.

    Returns:
        bool:
            Whether the member is a moderator or not.
    """
    if not isinstance(member, discord.Member):
        return False

    return bool(discord.utils.get(member.roles, id=int(constants.ROLE_ID_MODERATOR)))


def sanitize_str(
    message: str, sub_newlines: bool = True, sub_emojis: bool = True
) -> str:
    """Sanitizes a string, making it safe to be displayed.
    By default, all options are ``True``.

    Args:
        message (str):
            The message to sanitize.
        sub_newlines (bool):
            Whether to substitute newlines with a single space character.
        sub_emojis (bool):
            Whether to substitute emojis with an empty string.

    Returns:
        str: The sanitized string.
    """
    if sub_newlines:
        newline_pattern = re.compile(r"(\n( )*)+")
        message = re.sub(newline_pattern, " ", message)

    if sub_emojis:
        emoji_pattern = re.compile(r"(:(\w):)+", re.ASCII)
        message = re.sub(emoji_pattern, "", message)

    return message


def setup(bot):
    bot.add_cog(RemindMeCog(bot))
