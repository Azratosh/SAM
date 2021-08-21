"""Constants for the remindme command and its parser.

This file contains all the constants used for the ``remindme`` command and
its parser. Every constant is to be used exclusively within the ``remindme``
package.

Note:
    Translations for keywords could be handled in a more elegant way,
    preferably through something like the ``gettext`` package. Implementing
    these translations might require changes to the keywords' data structures
    as well.

"""

import datetime
import re

REMINDER_EMOJI = "\U0001f4c5"
REMINDER_DT_FORMAT = "%Y-%m-%d %H:%M:%S"
REMINDER_DT_MESSAGE_FORMAT = "%d.%m.%y, %H:%M:%S"

TOMORROW_KEYWORDS: tuple[str, ...] = ("tomorrow", "morgen")
"""Keywords that indicate that a reminder is for the next day."""

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
"""Various times of the day and their matching keywords, arbitrarily chosen."""

DURATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "years": ("y", "years", "year", "jahre", "jahr"),
    "months": ("m", "months", "month", "monate", "monat"),
    "weeks": ("w", "weeks", "week", "wochen", "woche"),
    "days": ("d", "days", "day", "tage", "tag"),
    "hours": ("h", "hours", "hour", "stunden", "stunde"),
    "minutes": ("min", "minutes", "minute", "minuten"),
}
"""Keywords for specifying durations as well as their alternate forms.

Each key corresponds to a parameter that :obj:`~.relativedelta.relativedelta`
may take. 
"""

PATTERNS_DATE: list[tuple[re.Pattern, str]] = [
    (re.compile(_regex, re.IGNORECASE), _format)
    for _regex, _format in [
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
]
"""A list of tuples containing a pattern and a format string, matching for a date.

Each pattern is matched with its corresponding datetime format string that is 
used to convert the regex pattern's match object to a :obj:`datetime.datetime` 
object using :obj:`datetime.datetime.strptime`.

These pairs are used to parse various formats of dates that users might specify,
including dates in ISO, US, or European format. More formats may be added if
required.
"""

PATTERNS_TIME = [
    (re.compile(_regex, re.IGNORECASE), _format)
    for _regex, _format in [
        (r"(?P<time>([012]?\d:[012345]\d) (AM|PM))", "%I:%M %p"),
        (r"(?P<time>([012]?\d:[012345]\d)(AM|PM))", "%I:%M%p"),
        (r"(?P<time>[012]?\d:[012345]\d)(?![ ]?(AM|PM))", "%H:%M"),
    ]
]
"""A list of tuples containing a pattern and a format string, matching for time.

Each pattern is matched with its corresponding datetime format string that is 
used to convert the regex pattern's match object to a :obj:`datetime.datetime` 
object using :obj:`datetime.datetime.strptime`.

These pairs are used to parse two different time formats that users might
specify, either 24-hour clock or 12-hour clock, including an additional regex
for the 12-hour clock format, for fault-tolerance's sake.
"""
