from itertools import zip_longest
from typing import Optional, Union

import datetime
import re

from dateutil import relativedelta

# Note regarding constants in general:
# All of the following constants are to be used exclusively by the parser
# and have been written in such a way.

# Note regarding keywords:
# Translations for any of the following keywords could be handled in a more
# elegant way. This might require some changes to their data structures as well.

TOMORROW_KEYWORDS: tuple[str, ...] = ("tomorrow", "morgen")
"""
Keywords that indicate that a reminder is for tomorrow.
"""

PART_OF_DAY_KEYWORDS: dict[datetime.time, tuple[str, ...]] = {
    datetime.time(5): ("dawn", "tagesanbruch"),
    datetime.time(7): ("morning", "früh", "frueh"),
    datetime.time(10): ("forenoon", "vormittag"),
    datetime.time(12): ("noon", "midday", "lunchtime", "mittag"),
    datetime.time(14): ("afternoon", "nachmittag"),
    datetime.time(16): ("teatime", "teezeit"),
    datetime.time(18): ("evening", "abend"),
    datetime.time(22): ("night", "nacht"),
    datetime.time(0): ("midnight", "mitternacht"),
}
"""
Various times of the day and their corresponding keywords, arbitrarily chosen.
"""

DURATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "years": ("y", "years", "year", "jahre", "jahr"),
    "months": ("m", "months", "month", "monate", "monat"),
    "weeks": ("w", "weeks", "week", "wochen", "woche"),
    "days": ("d", "days", "day", "tage", "tag"),
    "hours": ("h", "hours", "hour", "stunden", "stunde"),
    "minutes": ("min", "minutes", "minute", "minuten"),
}
"""
Keywords for specifying durations as well as their alternate forms.
Each key corresponds to a parameter that :obj:`~.relativedelta.relativedelta`
may take. 
"""
# Notice the negative lookahead assertion in the regex for format "%d.%m"
# This is to prevent matching the beginning of e.g. "1.5 hours"
REGEXES_DATE: list[tuple[str, str]] = [
    (r"(?P<date>\d\d\d\d-[01]?\d-[0123]?\d)", "%Y-%m-%d"),
    (r"(?P<date>\d\d-[01]?\d-[0123]?\d)", "%y-%m-%d"),
    (r"(?P<date>[01]?\d-[0123]?\d)", "%m-%d"),
    (r"(?P<date>[0123]?\d\.[01]?\d\.\d\d\d\d)", "%d.%m.%Y"),
    (r"(?P<date>[0123]?\d\.[01]?\d\.\d\d)", "%d.%m.%y"),
    (r"(?P<date>[0123]?\d\.[01]?\d.)", "%d.%m."),
    (r"(?P<date>[01]?\d/[0123]?\d/\d\d\d\d)", "%m/%d/%Y"),
    (r"(?P<date>[01]?\d/[0123]?\d/\d\d)", "%m/%d/%y"),
    (r"(?P<date>[01]?\d/[0123]?\d)", "%m/%d"),
]
"""
A list of regex-format pairs, where each regex is matched with its corresponding
datetime format string that is used to convert the regex's match object to
a :obj:`datetime.datetime` object using :obj:`datetime.datetime.strptime`.

These pairs are used to parse various formats of dates that users might specify,
including dates in ISO, US, or European format. More formats may be added if
required.
"""

REGEXES_TIME: list[tuple[str, str]] = [
    (r"(?P<time>([012]?\d:[012345]\d) (AM|PM))", "%I:%M %p"),
    (r"(?P<time>([012]?\d:[012345]\d)(AM|PM))", "%I:%M%p"),
    (r"(?P<time>[012]?\d:[012345]\d)(?![ ]?(AM|PM))", "%H:%M"),
]
"""
A list of regex-format pairs, where each regex is matched with its corresponding
datetime format string that is used to convert the regex's match object to
a :obj:`datetime.datetime` object using :obj:`datetime.datetime.strptime`.

These paris are used to parse two different time formats that users might
specify, either 24-hour clock or 12-hour clock, including an additional regex
for the 12-hour clock format, for fault-tolerance's sake.
"""

PATTERNS_DATE: list[tuple[re.Pattern, str]] = [
    (re.compile(_regex, re.IGNORECASE), _format) for _regex, _format in REGEXES_DATE
]
"""
The compiled version of :py:const:`REGEXES_DATE`.
"""

PATTERNS_TIME = [
    (re.compile(_regex, re.IGNORECASE), _format) for _regex, _format in REGEXES_TIME
]
"""
The compiled version of :py:const:`REGEXES_TIME`.
"""

REMINDER_DT_FINAL_FORMAT = "%Y-%m-%d %H:%M"


class ReminderParseError(ValueError):
    """
    Custom exception class allowing for more granular exception handling
    if required.

    Whenever this exception is thrown, the parsing process failed in an
    unrecoverable way, which *should* be caused by the user.
    """

    pass


def parse(
    text: str, ref_dt: Optional[datetime.datetime] = None
) -> Union[tuple[datetime.datetime, str], tuple[None, None]]:
    """
    .. todo::
        * docs: add clickable link to reminder specification

    Top-level routine that tries to parse ``message`` according to the
    reminder specification. A couple different parsing methods are attempted
    until one succeeds.

    Args:
        text (str): The string to attempt to parse.
        ref_dt (Optional[datetime.datetime]): The reference ``datetime`` in regard
            to which the final ``datetime`` object should be constructed. If not
            provided, the current local datetime is used instead.

    Returns:
        tuple[datetime.datetime, str]:
            A tuple of the reminder's ``datetime`` and message. The message string
            may be empty. If nothing could be parsed, a tuple of ``None`` is
            returned instead.

    Raises:
        ReminderParseError: If an error happens during the entire parsing process.
    """
    text_ = text.strip()
    if ref_dt is None:
        ref_dt = datetime.datetime.now()

    is_tomorrow = False

    # 0: Initial check for "tomorrow"
    #       -> only part of day or time may follow after
    for keyword in TOMORROW_KEYWORDS:
        if text_.startswith(keyword):
            text_ = text_[len(keyword) :].strip()
            is_tomorrow = True
            break

    # 1: Attempting to extract quoted text if given
    #       -> if text was not quoted, returned time_spec contains reminder text
    time_spec, quoted_text = parse_reminder_message(text_)

    # 2: Attempting to parse the part of day (morning, afternoon)
    #       -> if text was not quoted, remaining_message contains reminder text
    parsed_datetime, remaining_message = parse_day_part(
        time_spec, is_tomorrow, ref_dt=ref_dt
    )

    # 3: Try parsing for a timestamp instead if no part of day was found
    if parsed_datetime is None:
        parse_method = "time" if is_tomorrow else "datetime"

        parsed_datetime, remaining_message = parse_timestamp(
            time_spec, parse_method=parse_method, ref_dt=ref_dt
        )

    # 4: Try parsing for a series of durations if no timestamp was found
    if parsed_datetime is None and not is_tomorrow:
        parsed_datetime, remaining_message = parse_duration(
            time_spec, bool(quoted_text), ref_dt=ref_dt
        )

    if parsed_datetime is None:
        raise ReminderParseError(
            "Erinnerung ist nicht lesbar. Bitte überprüfe deine Eingabe."
        )

    if quoted_text and remaining_message:
        raise ReminderParseError(f"Unlesbares Argument gefunden: {remaining_message}")
    elif not quoted_text and not remaining_message:
        raise ReminderParseError("Deine Erinnerung muss eine Nachricht enthalten.")

    # 5: Ensure that date is incremented by one day if reminder is for next day
    if (
        is_tomorrow
        and parsed_datetime.date() < (ref_dt + datetime.timedelta(days=1)).date()
    ):
        parsed_datetime += datetime.timedelta(days=1)

    # 6: Sanitize resulting datetime, truncating seconds and microseconds
    parsed_datetime = datetime.datetime.strptime(
        parsed_datetime.strftime(REMINDER_DT_FINAL_FORMAT), REMINDER_DT_FINAL_FORMAT
    )

    reminder_message = quoted_text or remaining_message

    return parsed_datetime, reminder_message


def parse_reminder_message(text: str) -> tuple[str, str]:
    """
    Attempts to parse the time specification and the reminder's text from
    the given ``text``, returned as a tuple of strings.

    The time spec string is to be processed further through other
    parsing functions.

    Args:
        text (str): The string to attempt to parse.

    Returns:
        tuple[str, str]: The time specification and the reminder's message.
            If the reminder's text wasn't quoted, an empty string is returned
            as message, so as to let the other parsing functions handle message
            extraction.

    Raises:
        ReminderParseError: If additional arguments are found after the quoted
            text or if the number of quotes is neither 0 or 2.
    """

    text_ = text.strip()

    quote_character = '"'
    quote_count = text_.count(quote_character)

    # Case 0: No quotation marks, nothing to do
    if quote_count == 0:
        return text, ""

    # Case 1: Two or more quotation marks may be handled through finding the
    #         first and last one.
    #         time_spec = text before the first quote
    #         message   = text within the first and last quote
    #         Anything after the last quote is considered an invalid argument.
    elif quote_count >= 2:
        i_message_start = text_.find(quote_character)
        i_message_end = text_.rfind(quote_character)

        time_spec = text_[:i_message_start].strip()
        message = text_[i_message_start + 1 : i_message_end]

        remainder = text_[i_message_end + 1 :].strip()
        if remainder:
            raise ReminderParseError(
                "Ungültiges Argument nach Text in Anführungszeichen gefunden: "
                f"`{remainder}`"
            )

        return time_spec, message

    else:
        raise ReminderParseError(
            f"Nachricht wurde nicht korrekt in Anführungszeichen gesetzt: {text_}\n"
            "Verwende bitte entweder keine oder zwei Anführungszeichen."
        )


def parse_day_part(
    text: str, is_tomorrow: bool = False, ref_dt: Optional[datetime.datetime] = None
) -> Union[tuple[datetime.datetime, str], tuple[None, None]]:
    """
    Attempts to parse a part-of-day-keyword from the beginning of the given
    ``text``, like ``noon`` or ``evening``.

    If the matching keyword corresponds to a part of the day that is already in
    the past, the next day's part is chosen instead. For example, if the keyword is
    ``morning`` but it's already 13:00, the ``datetime`` corresponding to
    ``morning`` of the following day is returned.

    Args:
        text (str): The string to attempt to parse.
        is_tomorrow (bool): Whether the part of day is tomorrow or not.
        ref_dt (Optional[datetime.datetime]): The reference ``datetime`` in regard
            to which the final ``datetime`` object should be constructed. If not
            provided, the current local datetime is used instead.

    Returns:
        Union[tuple[datetime.datetime, str], tuple[None, None]]:
            A tuple of the reminder's ``datetime`` and message. The message string
            may be empty. If nothing could be parsed, a tuple of ``None`` is
            returned instead.
    """
    text_ = text.lstrip()
    if ref_dt is None:
        ref_dt = datetime.datetime.now()

    for time_, keywords in PART_OF_DAY_KEYWORDS.items():
        for keyword in keywords:
            if text_.lower().startswith(keyword):

                # Special Case: midnight + is_tomorrow --> must be two days ahead
                if is_tomorrow and time_ == datetime.time(0):
                    date_ = (ref_dt + datetime.timedelta(days=2)).date()
                elif is_tomorrow or time_ <= ref_dt.time():
                    date_ = (ref_dt + datetime.timedelta(days=1)).date()
                else:
                    date_ = ref_dt.date()

                return (
                    datetime.datetime.combine(date_, time_),
                    text_[len(keyword) :].lstrip(),
                )

    else:
        return None, None


def parse_timestamp(
    text: str, /, parse_method="datetime", ref_dt: Optional[datetime.datetime] = None
) -> Union[tuple[datetime.datetime, str], tuple[None, None]]:
    """
    Attempts to parse a timestamp from the given ``text`` according to the
    ``parse_method`` used.

    Args:
        text (str): The string to attempt to parse.
        parse_method (str): The parse method to use. Must be either ``time``,
            ``date``, or ``datetime``. Default: ``datetime``.
        ref_dt (Optional[datetime.datetime]): The reference ``datetime`` in regard
            to which the final ``datetime`` object should be constructed. If not
            provided, the current local datetime is used instead.

    Returns:
        Union[tuple[datetime.datetime, str], tuple[None, None]]:
            A tuple of the reminder's ``datetime`` and message. The message string
            may be empty. If nothing could be parsed, a tuple of ``None`` is
            returned instead.
    """

    if parse_method not in ("time", "date", "datetime"):
        # Never the user's fault, so ValueError
        raise ValueError(f'{parse_method =} - must be "time", "date", or "datetime"')

    text = text.strip()
    if ref_dt is None:
        ref_dt = datetime.datetime.now()

    # Note: _match_timestamp_date / _match_timestamp_time use re.match(),
    #       which means that only the first match is returned, and the match
    #       can only happen at the beginning of the string.
    #       At first glance, the logic down below may seem weird, but it does
    #       ensure that the parsing happens exactly as expected. This allows
    #       both the date and time to be parsed irrespective of order.

    # Try matching for date first, then time
    date_str, date_format = _match_timestamp_date(text)
    if date_str:
        if parse_method not in ("datetime", "date"):
            raise ReminderParseError(
                "Der Zeitstempel enthält ein Datum, obwohl nur eine Uhrzeit verlangt wird."
            )

        date_str_n, date_format_n = _normalize_date_str(date_str, date_format, ref_dt)
        date_ = datetime.datetime.strptime(date_str_n, date_format_n).date()

        if date_ < ref_dt.date():
            raise ReminderParseError(
                "Das Datum kann nicht in der Vergangenheit liegen."
            )

        text = text[len(date_str) :].lstrip()

        time_str, time_format = _match_timestamp_time(text)
        if time_str:
            if parse_method != "datetime":
                raise ReminderParseError(
                    "Der Zeitstempel enthält eine Uhrzeit, obwohl nur ein Datum verlangt wird."
                )

            time_ = datetime.datetime.strptime(time_str, time_format).time()

            if time_ <= ref_dt.time() and date_ == ref_dt.date():
                raise ReminderParseError(
                    "Die Uhrzeit darf nicht in der Vergangenheit liegen."
                )

            text = text[len(time_str) :].lstrip()

        else:
            if not date_ > ref_dt.date():
                raise ReminderParseError(
                    "Das Datum muss in der Zukunft liegen wenn keine Zeit angegeben wird."
                )

            time_ = datetime.time(9, 0)

        return datetime.datetime.combine(date_, time_), text

    # If no date was matched, try matching for time, then date
    time_str, time_format = _match_timestamp_time(text)
    if time_str:

        time_ = datetime.datetime.strptime(time_str, time_format).time()
        text = text[len(time_str) :].lstrip()

        date_str, date_format = _match_timestamp_date(text)
        if date_str:
            if parse_method != "datetime":
                raise ReminderParseError(
                    "Der Zeitstempel enthält ein Datum, obwohl nur eine Uhrzeit verlangt wird."
                )

            date_str_n, date_format_n = _normalize_date_str(
                date_str, date_format, ref_dt
            )
            date_ = datetime.datetime.strptime(date_str_n, date_format_n).date()

            if date_ < ref_dt.date():
                raise ReminderParseError(
                    "Das Datum darf nicht in der Vergangenheit liegen."
                )

            if time_ <= ref_dt.time() and date_ == ref_dt.date():
                raise ReminderParseError(
                    "Die Uhrzeit darf nicht in der Vergangenheit liegen."
                )

            text = text[len(date_str) :].lstrip()

        elif time_ <= ref_dt.time():
            date_ = (ref_dt + datetime.timedelta(days=1)).date()

        else:
            date_ = ref_dt.date()

        return datetime.datetime.combine(date_, time_), text

    return None, None


def _match_timestamp_date(text: str) -> Union[tuple[str, str], tuple[None, None]]:
    """
    Iterates over all date regex patterns, attempting to match any of them on the
    given ``text``.

    .. note::
        Due to the behaviour of :obj:`re.Pattern.match`, the given string is
        always attempted to be matched from the *beginning.*

        This is necessary for the parsing logic used in :func:`parse_timestamp`.

    Args:
        text (str): The string to attempt to match.

    Returns:
        Union[tuple[str, str], tuple[None, None]]:
            A tuple of the matched date string and its regex pattern's corresponding
            format string, or a tuple of ``None`` if no match was found.
    """
    text_ = text.strip()
    for pattern_, format_ in PATTERNS_DATE:
        match = pattern_.match(text_)
        if match:
            return match["date"], format_

    else:
        return None, None


def _match_timestamp_time(text: str) -> Union[tuple[str, str], tuple[None, None]]:
    """
    Iterates over all time regex patterns, attempting to match any of them on the
    given ``text``.

    Additionally, if the string starts with ``24:00``, it is interpreted as
    ``00:00`` for user friendliness.

    .. note::
        Due to the behaviour of :obj:`re.Pattern.match`, the given string is
        always attempted to be matched from the *beginning.*

        This is necessary for the parsing logic used in :func:`parse_timestamp`.

    Args:
        text (str): The string to attempt to match.

    Returns:
        Union[tuple[str, str], tuple[None, None]]:
            A tuple of the matched time string and its regex pattern's corresponding
            format string, or a tuple of ``None`` if no match was found.
    """
    text_ = text.strip().lower()
    if text_.startswith("24:00"):
        text_ = "00:00" + text_[5:]  # we being nice here

    for _pattern, _format in PATTERNS_TIME:
        match = _pattern.match(text_)
        if match:
            return match["time"], _format

    else:
        return None, None


def _normalize_date_str(
    date_str: str, date_format_str: str, ref_dt: datetime.datetime
) -> tuple[str, str]:
    """
    Internal function.

    If the given date format string does not contain a year placeholder
    (``%y`` or ``%Y``), the year of the reference datetime object is appended
    to the date string and a corresponding placeholder to its format string.

    Otherwise, both strings are left unchanged.

    Args:
        date_str (str): A string representing a date.
        date_format_str (str): A format string that matches the date string.
        ref_dt (datetime.datetime): The reference datetime in regard to which
            to add the missing year.

    Returns:
        tuple[str, str]: A date string and its corresponding format string.
    """
    if "%y" not in date_format_str and "%Y" not in date_format_str:
        year = ref_dt.strftime(" %Y")
        return date_str + year, date_format_str + " %Y"
    return date_str, date_format_str


def parse_duration(
    text: str, was_quoted: bool = False, ref_dt: Optional[datetime.datetime] = None
) -> Union[tuple[datetime.datetime, str], tuple[None, None]]:
    """
    Attempts to parse the provided ``text``, interpreting it as a series of
    duration specifiers.

    These duration specifiers are user-provided tuples in the form of
    ``(duration, keyword)``, with the duration being a numeric value and the
    keyword being a string. Check the reminder specification for more information.

    .. todo::
        * docs: add clickable link to reminder specification


    If the text contained a reminder message in quotes, a slightly more
    performant parsing method is chosen. Otherwise, a method that involves more
    complicated guesswork is used instead.

    .. warning::
        Ensure that ``was_quoted`` is always set correctly in order to avoid
        potential side effects.

    Args:
        text (str): The string to attempt to parse.
        was_quoted (bool): Whether the given string was quoted before or not.
        ref_dt (Optional[datetime.datetime]): The reference ``datetime`` in regard
            to which the final ``datetime`` object should be constructed. If not
            provided, the current local datetime is used instead.

    Returns:
        Union[tuple[datetime.datetime, str], tuple[None, None]]:
            A tuple of the reminder's ``datetime`` and message. The message string
            may be empty. If nothing could be parsed, a tuple of ``None`` is
            returned instead.

    Raises:
        ReminderParseError:

    """
    if ref_dt is None:
        ref_dt = datetime.datetime.now()

    duration_spec = {}
    message = ""

    # These errors also contain the value-keyword pairs that caused them
    # as additional argument (error.args[1])
    duplicate_keyword_errors: list[ReminderParseError] = []

    text_parts = text.split()

    if was_quoted:  # We skip the guesswork here
        # Since quoted text has been removed, the text is
        # assumed to be a time spec only, which always has even length
        if len(text_parts) % 2:
            raise ReminderParseError(f"Ungültige Zeitangabe: {text}")

        text_part_iter = iter(text_parts)

        for value, keyword in zip(text_part_iter, text_part_iter):
            parsed_value = _parse_duration_value(value)
            parsed_keyword = _parse_duration_keyword(keyword)

            if parsed_keyword in duration_spec:
                duplicate_keyword_errors.append(
                    ReminderParseError(
                        "Mehrfache Zeitangabe: "
                        f'Ein Wert für "{value} {keyword}" existiert bereits.',
                        (value, keyword),
                    )
                )

            else:
                duration_spec[parsed_keyword] = parsed_value

    else:
        # Guesswork: Progressively split the text up and parse value-keyword
        # pairs. Return timestamp and reminder message based on various
        # exceptions that appear during parsing.
        value_error = None
        keyword_error = None

        parsed_tokens: list[str] = []

        remainder = text
        while remainder:
            pieces = remainder.split(maxsplit=2)

            if len(pieces) == 3:
                value, keyword, remainder = pieces

            elif len(pieces) == 2:
                remainder = ""
                value, keyword = pieces

            elif len(pieces) == 1:
                remainder = ""
                value = pieces[0]
                keyword = ""

            else:
                break

            previous_value_error = value_error
            previous_keyword_error = keyword_error

            # Attempt to parse value and keyword, store exceptions
            try:
                parsed_value = _parse_duration_value(value)
            except ReminderParseError as e:
                value_error = e
                parsed_value = None

            try:
                parsed_keyword = _parse_duration_keyword(keyword)
                if parsed_keyword in duration_spec:
                    duplicate_keyword_errors.append(
                        ReminderParseError(
                            "Mehrfache Zeitangabe: "
                            f"Ein Wert für `{value} {keyword}` existiert bereits.",
                            (value, keyword),
                        )
                    )
            except ReminderParseError as e:
                keyword_error = e
                parsed_keyword = None

            if parsed_value and parsed_keyword:

                # If the current iteration succeeded and the previous one had
                # an error, we assume that the timespec itself contains
                # an invalid token --> throw exception
                if previous_value_error or previous_keyword_error:
                    if duplicate_keyword_errors:
                        error_message = (
                            f"{str(previous_value_error or previous_keyword_error)}"
                        )

                        if len(duplicate_keyword_errors) > 1:
                            error_message += f"\nMehrfache Zeitangaben: "
                            error_message += ", ".join(
                                f"`{error.args[1][0]} {error.args[1][1]}`"
                                for error in duplicate_keyword_errors
                            )
                        else:
                            error_message += f"\n{duplicate_keyword_errors[0].args[0]}"

                        raise ReminderParseError(error_message)

                    else:
                        raise previous_value_error or previous_keyword_error

                else:
                    parsed_tokens.append(value)
                    parsed_tokens.append(keyword)
                    duration_spec[parsed_keyword] = parsed_value

            elif parsed_value or parsed_keyword:
                # Tokens do not count as parsed, because one caused an exception.
                # --> either message started, or an invalid keyword was used

                # If either variable could be parsed, but not both, and the previous
                # iteration had an error, we can safely break
                if previous_value_error or previous_keyword_error:
                    break
                else:
                    continue
            else:
                # Always break when both parses fail -> message started
                break

        message = _extract_message_after_tokens(text, parsed_tokens)

    if duplicate_keyword_errors:
        if len(duplicate_keyword_errors) > 1:
            error_message = "Mehrfache Zeitangaben:"
            for error in duplicate_keyword_errors:
                error_message += f"\n:red_circle: {error.args[1][0]} {error.args[1][1]}"
            raise ReminderParseError(error_message)
        else:
            raise duplicate_keyword_errors[0]
    if not duration_spec:
        return None, None

    parsed_datetime = ref_dt + relativedelta.relativedelta(**duration_spec)
    return parsed_datetime, message


def _parse_duration_value(duration_value: str) -> float:
    """
    Attempts to convert a string into a float.

    .. note::
        This function was made to be used specifically in :func:`parse_duration`
        in order to create :obj:`ReminderParseError` exceptions which are to
        handled during the parsing process.

    Args:
        duration_value (str): The string to attempt to convert into a float.

    Returns:
        float: The converted float.

    Raises:
        ReminderParseError: If the conversion failed.
    """
    try:
        return float(duration_value)
    except ValueError:
        raise ReminderParseError(
            "Der angegebene Wert konnte nicht in eine Zahl konvertiert werden:\n"
            f"`{duration_value}`"
        )


def _parse_duration_keyword(duration_keyword: str):
    """
    Attempts to find a matching duration key to be used as an argument in
    :obj:`~.relativedelta.relativedelta` corresponding to the keyword given.

    .. note::
        This function was made to be used specifically in :func:`parse_duration`
        in order to create :obj:`ReminderParseError` exceptions which are to
        handled during the parsing process.

    Args:
        duration_keyword (str): The keyword for which to find a valid key.

    Returns:
        str: The matching key.

    Raises:
        ReminderParseError: If no corresponding key could be found.
    """
    duration_keyword_ = duration_keyword.lower()
    for key, variations in DURATION_KEYWORDS.items():
        if duration_keyword_ in variations:
            return key

    raise ReminderParseError(
        "Das angegebene Stichwort beschreibt keine gültige Dauer: "
        f"`{duration_keyword}`"
    )


def _extract_message_after_tokens(text: str, token_list: list[str]) -> str:
    """
    Extracts the reminder's message by removing every token from ``text``.

    Args:
        text (str): The string of which to remove the parsed tokens from.
        token_list (list[str]): The list of parsed tokens.

    Returns:
        str: The reminder's message.
    """
    text_ = text.strip()
    for token in token_list:
        text_ = text_[len(token) :].lstrip()
    return text_
