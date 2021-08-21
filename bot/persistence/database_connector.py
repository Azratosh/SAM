"""Contains logic for connecting to and manipulating the database."""

import datetime
import uuid
from sqlite3 import Error
from typing import List, Optional, Iterator, Iterable, Generator

from bot import constants
from bot.moderation import ModmailStatus
from bot.feedback import SuggestionStatus
from bot.persistence import queries
from .database_manager import DatabaseManager


class DatabaseConnector:
    """Class used to communicate with the database.

    The database is created and initialized using the __init__ method. The other methods support getting or adding
    properties to the database.
    """

    def __init__(self, db_file: str, init_script: Optional[str]):
        """Create a database connection to a SQLite database and create the default tables form the SQL script in
        init_db.sql.

        Args:
            db_file (str): The filename of the SQLite database file.
            init_script (Optional[str]): Optional SQL script filename that will be run when the method is called.
        """
        if db_file is None:
            raise Error("Database filepath and/or filename hasn't been set.")

        self._db_file = db_file
        with DatabaseManager(self._db_file) as db_manager:
            if init_script:
                queries_ = self.parse_sql_file(init_script)
                for query in queries_:
                    try:
                        db_manager.execute(query)
                    except Error as error:
                        print("Command could not be executed, skipping it: {0}".format(error))

    def add_member_warning(self, user_id: int, timestamp: datetime.datetime, reason: Optional[str]):
        """Adds a warning to the table "MemberWarning".

        Args:
            user_id (int): The id of the member who has been warned.
            timestamp (datetime.datetime): Timestamp representing the moment when the member was warned.
            reason (Optional[str]): The reason provided by the moderator why the member was warned.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_MEMBER_WARNING, (user_id, timestamp, reason))
            db_manager.commit()

    def remove_member_warning(self, warning_id: int):
        """Removes the warning with the specified id from the table "MemberWarning".

        Args:
            warning_id (int): The id of the warning which should be removed.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.DELETE_MEMBER_WARNING, (warning_id,))
            db_manager.commit()

    def remove_member_warnings(self, user_id: int):
        """Removes all warnings of a member from the table "MemberWarning".

        Args:
            user_id (int): The id of the member whose warnings should be removed.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.DELETE_MEMBER_WARNINGS, (user_id,))
            db_manager.commit()

    def get_warning_userid(self, warning_id: int) -> Optional[int]:
        """Gets the id of the member which received the warning with the specified id.

        Args:
            warning_id (int): The id of warning whose receiver needs to be identified.

        Returns:
            Optional[int]: The id of the member who has been warned.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_WARNING_USERID, (warning_id,))

            row = result.fetchone()
            if row:
                return int(row[0])
            return None

    def get_member_warnings(self, user_id: int) -> Optional[List[tuple]]:
        """Gets all the warnings of a specific member.

        Args:
            user_id (int): The id of the member whose warnings have been requested.

        Returns:
            Optional[List[tuple]]: A list containing the id of the warning, the timestamp when it happened and the
                                   reason provided by the moderator.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_MEMBER_WARNINGS, (user_id,))

            rows = result.fetchall()
            if rows:
                return rows
            return None

    def add_member_name(self, user_id: int, name: str, timestamp: datetime.datetime):
        """Adds a members old nickname to the table "MemberNameHistory".

        Args:
            user_id (int): The id of the member whose nickname has changed.
            name (str): The old nickname used before the change.
            timestamp (datetime.datetime): A timestamp representing when the nickname has been changed.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_MEMBER_NAME, (user_id, name, timestamp))
            db_manager.commit()

    def get_member_names(self, user_id: int) -> Optional[List[tuple]]:
        """Gets all the nicknames used by a member from the table "MemberNameHistory".

        Args:
            user_id (int): The id of the member whose nicknames have been requested.

        Returns:
            Optional[List[tuple]]: A list containing tuples consisting of the nickname and the timestamp representing
                                   when the name has been replaced.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_MEMBER_NAMES, (user_id,))

            rows = result.fetchall()
            if rows:
                return rows
            return None

    def add_reminder_job(
        self,
        job_id: uuid.UUID,
        timestamp: datetime.datetime,
        message: str,
        bot_msg_id: int,
    ):
        """
        Adds a new reminder job to the table *RemindmeJobs*.

        Whenever a record is added, a corresponding job should be added to the
        scheduler.

        Args:
            job_id (uuid.UUID): The UUID of the job. This is the same UUID that
                must be set as the scheduler's job ID.
            timestamp (datetime.datetime): The date and time at which the reminder
                should be issued.
            message (str): The reminder's message.
            bot_msg_id (int): The ID of the *discord.Message* the bot had posted.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(
                queries.INSERT_REMINDER_JOB,
                (str(job_id), str(timestamp), message, bot_msg_id),
            )
            db_manager.commit()

    def remove_reminder_job(self, job_id: uuid.UUID):
        """
        Removes a reminder job from the table *RemindmeJobs*.

        Whenever a record is deleted, the scheduler's corresponding job should
        also be removed.

        Args:
            job_id (uuid.UUID): The UUID of the job to remove. This is the same
                UUID that must have been set as the scheduler's job ID.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.REMOVE_REMINDER_JOB, (str(job_id),))
            db_manager.commit()

    def get_reminder_jobs(
        self, job_ids: Optional[Iterable[uuid.UUID]] = None
    ) -> Generator[tuple, None, None]:
        """
        Fetches the specified jobs from the table *RemindmeJobs*. If no jobs
        are specified, fetches all jobs.

        Args:
            job_ids (Optional[Iterable[uuid.UUID]]):
                An optional list of reminder job UUIDs.

        Returns:
            Generator[tuple, None, None]: A generator that yields tuples, each
                containing a reminder's job UUID, timestamp, and message.
        """
        with DatabaseManager(self._db_file) as db_manager:
            if job_ids is not None:
                result = db_manager.execute(
                    queries.GET_REMINDER_JOBS_CONDITIONAL.format(
                        ", ".join("?" for _ in job_ids)
                    ),
                    tuple(str(job_id) for job_id in job_ids),
                )
            else:
                result = db_manager.execute(queries.GET_REMINDER_JOBS)
            return (
                (
                    uuid.UUID(row[0]),
                    datetime.datetime.strptime(row[1], constants.REMINDER_DT_FORMAT),
                    row[2],
                    int(row[3]),
                )
                for row in result.fetchall()
            )

    def add_reminder_for_user(self, job_id: uuid.UUID, user_id: int):
        """
        Adds a reminder for a user to the table *RemindmeUserReminders*.

        One must ensure that the reminder job already exists in the `RemindmeJobs`
        table.

        Args:
            job_id (uuid.UUID): The UUID of the job.
            user_id (int): The user's ID to associate with the given job.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_REMINDER_FOR_USER, (str(job_id), user_id))
            db_manager.commit()

    def remove_reminder_for_user(self, job_id: uuid.UUID, user_id: int):
        """
        Removes a reminder for a user from the table *RemindmeUserReminders*.

        Args:
            job_id (uuid.UUID): The UUID of the job.
            user_id (int): The user's ID to associate with the given job.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.REMOVE_REMINDER_FOR_USER, (str(job_id), user_id))
            db_manager.commit()

    def get_reminders_for_users(
        self, user_ids: Optional[list[int]] = None
    ) -> Generator[tuple, None, None]:
        """
        Fetches all reminders set for the given user IDs from the table
        *RemindmeUserReminders*.

        Args:
            user_ids (Optional[list[int]]): The user IDs to query for.

        Returns:
            Generator[tuple, None, None]: A generator that yields tuples, each
                containing a reminder job ID and user ID.
        """
        with DatabaseManager(self._db_file) as db_manager:
            if user_ids:
                result = db_manager.execute(
                    queries.GET_REMINDERS_FOR_USER_CONDITIONAL.format(
                        ", ".join("?" for _ in user_ids)
                    ),
                    tuple(user_id for user_id in user_ids),
                )
            else:
                result = db_manager.execute(queries.GET_REMINDERS_FOR_USER)

            return ((uuid.UUID(row[0]), int(row[1])) for row in result.fetchall())

    def remove_many_reminder_for_user(
        self, job_user_tuples: list[tuple[uuid.UUID, int]]
    ):
        """
        Removes many reminders for many users from the table *RemindmeUserReminders*.

        Args:
            job_user_tuples (list[tuple[uuid.UUID, int]]):
                A list of tuples, each containing a reminder job's UUID and the
                user's ID.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.executemany(
                queries.REMOVE_REMINDER_FOR_USER,
                ((str(job_id), int(user_id)) for job_id, user_id in job_user_tuples),
            )
            db_manager.commit()

    def get_reminder_jobs_for_user(
        self, user_id: int
    ) -> Generator[uuid.UUID, None, None]:
        """
        Fetches all reminder jobs from table *RemindmeJobs* that are associated
        with a user.

        Args:
            user_id (int): The user ID to fetch the reminder jobs for.

        Returns:
            Generator[uuid.UUID, None, None]: A generator that yields reminder
                jobs that correspond to the given user ID.
        """
        with DatabaseManager(self._db_file) as db_manager:
            return (
                uuid.UUID(row[0])
                for row in db_manager.execute(
                    queries.GET_REMINDER_JOBS_FOR_USER, (user_id,)
                ).fetchall()
            )

    def get_users_for_reminder_job(
        self, job_id: uuid.UUID
    ) -> Generator[int, None, None]:
        """
        Fetches all user IDs from table *RemindmeUserReminders* that are associated
        with a reminder job.

        Args:
            job_id (uuid.UUID): The reminder job's UUID to fetch the user IDs for.

        Returns:
            Generator[int, None. None]: A generator that yields user IDs.
        """
        with DatabaseManager(self._db_file) as db_manager:
            return (
                int(row[0])
                for row in db_manager.execute(
                    queries.GET_USERS_FOR_REMINDER_JOB, (str(job_id),)
                ).fetchall()
            )

    def add_module_role(self, role_id: int):
        """Adds a role to the table "ModuleRole".

        Args:
            role_id (int): The id of the role which should be added.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_MODULE_ROLE, (role_id,))
            db_manager.commit()

    def remove_module_role(self, role_id: int):
        """Removes a role from the table "ModuleRole".

        Args:
            role_id (int): The role id of the role which should be removed.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.REMOVE_MODULE_ROLE, (role_id,))
            db_manager.commit()

    def check_module_role(self, role_id: int) -> bool:
        """Check if there's an entry for the specified role in the table "ModuleRole".

        Args:
            role_id (int): The id of the role which needs to be checked.

        Returns:
            bool: A boolean indicating if the role has been whitelisted.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.CHECK_IF_MODULE_ROLE, (role_id,))
            row = result.fetchone()

            return bool(row[0])

    def get_reaction_role(self, msg_id: int, emoji: str) -> Optional[int]:
        """Gets the role id for the specified reaction on a specific message.

        Args:
            msg_id (int): The id of the message which has been reacted to.
            emoji (str): The emoji of the reaction.

        Returns:
            Optional[int]: The id of the role associated with the given message + reaction.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_REACTION_ROLE, (msg_id, emoji))

            row = result.fetchone()
            if row:
                return int(row[0])
            return None

    def add_reaction_role(self, msg_id: int, emoji: str, role_id: int):
        """Adds information needed for a reaction role to the table "ReactionRole".

        Args:
            msg_id (int): The id of the message which users should react to.
            emoji (str): The emoji for the reaction role.
            role_id (int): The id of the role for the reaction role.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_REACTION_ROLE, (msg_id, emoji, role_id))
            db_manager.commit()

    def remove_reaction_role(self, msg_id: int, emoji: str):
        """Removes information needed for a reaction role from the table "ReactionRole".

        Args:
            msg_id (int): The id of the message which users should react to.
            emoji (str): The emoji for the specific reaction role.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.REMOVE_REACTION_ROLE, (msg_id, emoji))
            db_manager.commit()

    def clear_reaction_roles(self, msg_id: int) -> bool:
        """Removes all information needed for the reaction roles of a specific message from the table "ReactionRole".

        Args:
            msg_id (int): The id of the message which reaction roles should be removed.

        Returns:
            bool: A boolean indicating if any reaction roles have been deleted.
        """
        with DatabaseManager(self._db_file) as db_manager:
            affected_rows = db_manager.execute(queries.CLEAR_REACTION_ROLES, (msg_id,)).rowcount
            db_manager.commit()

            return affected_rows != 0

    def add_reaction_role_uniqueness_group(self, msg_id: int):
        """Adds the id of a message to the table "ReactionRoleGroup".

        The existence of a message id in this table indicates, that a user should only be able to have one of the
        specified reaction roles of a message at any time given.

        Args:
            msg_id (int): The id of the message which users can react to.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_REACTION_ROLE_UNIQUENESS_GROUP, (msg_id,))
            db_manager.commit()

    def remove_reaction_role_uniqueness_group(self, msg_id: int):
        """Removes the id of a message from the table "ReactionRoleGroup".

        The absence of a message id in this table indicates, that a user can have multiple reaction roles of this
        message at once.

        Args:
            msg_id (int): The id of the message which users can react to.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.REMOVE_REACTION_ROLE_UNIQUENESS_GROUP, (msg_id,))
            db_manager.commit()

    def is_reaction_role_uniqueness_group(self, msg_id: int) -> bool:
        """Checks if the reaction roles of a message have been declared as unique.

        If yes, this means that a user can only have one of these roles at any time given.

        Args:
            msg_id (int): The id of the message which users can react to.

        Returns:
            bool: A boolean indicating if the reaction roles of a message have been declared as unique.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.IS_REACTION_ROLE_UNIQUE, (msg_id,))
            row = result.fetchone()

            return bool(row[0])

    def add_suggestion(self, author_id: int, timestamp: datetime.datetime) -> int:
        """Adds a suggestion to the table "Suggestion".

        Args:
            author_id (int): The id of the user who submitted the suggestion.
            timestamp (datetime.datetime): A timestamp when this suggestion has been submitted.

        Returns:
            int: The row id of the new entry.
        """
        with DatabaseManager(self._db_file) as db_manager:
            row_id = db_manager.execute(queries.INSERT_SUGGESTION, (author_id, timestamp)).lastrowid
            db_manager.commit()

            return row_id

    def set_suggestion_message_id(self, suggestion_id: int, message_id: int):
        """Sets the message id of a specific suggestion.

        Args:
            suggestion_id (int): The id of the suggestion.
            message_id (int): The message id of the embed posted in the suggestion channel.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.SET_SUGGESTION_MESSAGE_ID, (message_id, suggestion_id))
            db_manager.commit()

    def get_suggestion(self, suggestion_id: int) -> Optional[tuple]:
        """Gets data regarding a suggestion with the specified id.

        Args:
            suggestion_id (int): The id of the suggestion.

        Returns:
            tuple: A tuple containing MessageID, StatusID and AuthorID of a suggestion in the table "Suggestion".
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_SUGGESTION_BY_ID, (suggestion_id,))

            row = result.fetchone()
            if row:
                return row
            return None

    def get_suggestion_status(self, message_id: int) -> Optional[SuggestionStatus]:
        """Gets the status of a suggestion with the specified message id.

        Args:
            message_id (int): The id of the message containing the suggestion embed.

        Returns:
            SuggestionStatus: The status of the suggestion.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_SUGGESTION_STATUS, (message_id,))

            row = result.fetchone()
            if row:
                return SuggestionStatus(row[0])
            return None

    def set_suggestion_status(self, suggestion_id: int, status: SuggestionStatus) -> bool:
        """Sets the status of a suggestion with the specified id.

        Args:
            suggestion_id (int): The id of the suggestion.
            status (SuggestionStatus): The new status of the suggestion.

        Returns:
            bool: A boolean representing if any rows have been changed
        """
        with DatabaseManager(self._db_file) as db_manager:
            affected_rows = db_manager.execute(queries.SET_SUGGESTION_STATUS, (status.value, suggestion_id)) \
                .rowcount
            db_manager.commit()
            return affected_rows != 0

    def get_all_suggestions_with_status(self, status: SuggestionStatus) -> Optional[List[tuple]]:
        """Gets data about all suggestions with the specified status.

        Args:
            status (SuggestionStatus): The status which the suggestions should have.

        Returns:
            Optional[List[tuple]]: A list containing data of all suggestions with the specified status.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_ALL_SUGGESTIONS_WITH_STATUS, (status.value,))

            rows = result.fetchall()
            if rows:
                return rows
            return None

    def add_modmail(self, msg_id: int, author: str, timestamp: datetime.datetime):
        """Inserts the username of the author and the message id of a submitted modmail into the database and
        sets its status to `Open`.

        Args:
            msg_id (int): The message id of the modmail which has been submitted.
            author (str): The username with the discriminator of the author.
            timestamp (datetime.datetime): A timestamp representing the moment when the message has been submitted.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_MODMAIL, (msg_id, author, timestamp))
            db_manager.commit()

    def get_modmail_status(self, msg_id: int) -> Optional[ModmailStatus]:
        """Returns the current status of a modmail associated with the message id given.

        Args:
            msg_id (int): The message id of the modmail.

        Returns:
            Optional[ModmailStatus]: The current status of the modmail.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_MODMAIL_STATUS, (msg_id,))

            row = result.fetchone()
            if row:
                return ModmailStatus(row[0])
            return None

    def change_modmail_status(self, msg_id: int, status: ModmailStatus):
        """Changes the status of a specific modmail with the given id.

        Args:
            msg_id (int): The message id of the modmail.
            status (ModmailStatus): The new status which should be set.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.CHANGE_MODMAIL_STATUS, (status.value, msg_id))
            db_manager.commit()

    def get_all_modmail_with_status(self, status: ModmailStatus) -> Optional[List[tuple]]:
        """Returns the message id of every modmail with the specified status.

        Args:
            status (ModmailStatus): The status to look out for.

        Returns:
            Optional[List[tuple]]: A list of all modmails with the the status specified.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_ALL_MODMAIL_WITH_STATUS, (status.value,))

            rows = result.fetchall()
            if rows:
                return rows
            return None

    def add_group_offer_and_requests(self, user_id: int, course: str, offered_group: int,
                                     requested_groups: Iterator[int]):
        """Adds new offer and requests for a course and a group.

        Args:
            user_id (int): The id of the offering user.
            course (str): The course for which the offer is.
            offered_group (str): The group that the user offers.
            requested_groups (List[str]): List of all groups the user would accept.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.INSERT_GROUP_OFFER, (user_id, course, offered_group))
            for group_nr in requested_groups:
                db_manager.execute(queries.INSERT_GROUP_REQUEST, (user_id, course, group_nr))
            db_manager.commit()

    def update_group_exchange_message_id(self, user_id: int, course: str, message_id: int):
        """Updates the message id in the GroupOffer table from 'undefined' to a valid value

        This function is necessary because the message_id can only be retrieved after the embed is sent, which happens
        after inserting in the db, to ensure constraints are fulfilled.

        Args:
            user_id (int): The id of the requesting user.
            course (str): The course that should be exchanged.
            message_id (int): The id of the message that contains the group exchange embed.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.UPDATE_GROUP_MESSAGE_ID, (message_id, user_id, course))
            db_manager.commit()

    def get_candidates_for_group_exchange(self, user_id: int, course: str, offered_group: int,
                                          requested_groups: Iterable[int]) -> Optional[List[tuple]]:
        """Gets all possible candidates for a group exchange offer.

        Args:
            user_id (int): The id of the user who created the request.
            course (str): The course for which the candidates are searched.
            offered_group (int): The group that the user offers.
            requested_groups (Iterable[int]): The groups that the user requests.

        Returns:
            Optional[List[tuple]]: A list containing user id and mesage id of potential group exchange candidates.
        """
        with DatabaseManager(self._db_file) as db_manager:
            parameter_list = [user_id, course, offered_group] + list(requested_groups)
            result = db_manager.execute(
                queries.FIND_GROUP_EXCHANGE_CANDIDATES.format(', '.join('?' for _ in requested_groups)),
                tuple(parameter_list)
            )
            rows = result.fetchall()
            if rows:
                return rows
            return None

    def get_group_exchange_message(self, user_id: int, course: int) -> Optional[int]:
        """Gets message id for the request of a user for a specific course.

        Args:
            user_id (int): The id of the user who created the request.
            course (int): The id of the channel referring to the course.

        Returns:
            Optional[int]: The id of the message containing the request.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_GROUP_EXCHANGE_MESSAGE, (user_id, course))

            rows = result.fetchone()
            if rows:
                return int(rows[0])
            return None

    def remove_group_exchange_offer(self, user_id: int, course: str):
        """Removes all entries of a group exchange offer and request for a user.

        Args:
            user_id (int): The user of which the request and offers should be deleted.
            course (str): The id of the course channel for which the entries should be deleted.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.REMOVE_GROUP_EXCHANGE_OFFER, (user_id, course))
            db_manager.execute(queries.REMOVE_GROUP_EXCHANGE_REQUESTS, (user_id, course))
            db_manager.commit()

    def get_group_exchange_for_user(self, user_id: int) -> Optional[List[tuple]]:
        """Executes a query to get all group exchange requests for a user.

        Args:
            user_id (int): The id of the user which requests should be fetched.

        Returns:
            Optional[List[tuple]]: A list containing all the group requests a user currently has.
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.GET_GROUP_EXCHANGE_FOR_USER, (user_id,))

            rows = result.fetchall()
            if rows:
                return rows
            return None

    def is_botonly(self, channel_id: int) -> bool:
        """Runs a query checking if a channel is marked as bot-only in the db.

        Args:
            channel_id (int): The id of the channel which should be checked.

        Returns:
            bool: true if the channel is botonly, false if not or no entry is found
        """
        with DatabaseManager(self._db_file) as db_manager:
            result = db_manager.execute(queries.IS_CHANNEL_BOTONLY, (channel_id,))
            row = result.fetchone()

            return bool(row[0])

    def activate_botonly(self, channel_id: int):
        """Executes a query that enables bot-only mode for a channel.

        Args:
            channel_id (int): The id of the channel for which bot-only mode should be activated.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.ACTIVATE_BOTONLY_FOR_CHANNEL, (channel_id,))
            db_manager.commit()

    def deactivate_botonly(self, channel_id: int):
        """Executes a query that disables bot-only for a channel.

        Args:
            channel_id (int): The id of the channel for which bot-only mode should be deactivated.
        """
        with DatabaseManager(self._db_file) as db_manager:
            db_manager.execute(queries.DEACTIVATE_BOTONLY_FOR_CHANNEL, (channel_id,))
            db_manager.commit()

    @staticmethod
    def parse_sql_file(filename: str) -> List[str]:
        """Parses a SQL script to read all queries/commands it contains.

        Args:
            filename (str): The filename of the init file. Can also be a path.

        Returns:
            List[str]: A list of strings with each entry being a SQL query.
        """
        file = open(filename, 'r')
        sql_file = file.read()
        file.close()
        return sql_file.split(';')
