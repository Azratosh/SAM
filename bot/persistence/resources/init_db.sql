CREATE TABLE IF NOT EXISTS Modmail(
    ID TEXT PRIMARY KEY,
    Author TEXT NOT NULL,
    StatusID SMALLINT NOT NULL DEFAULT 1,
    Timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Suggestion(
    ID INTEGER PRIMARY KEY,
    MessageID TEXT,
    AuthorID TEXT NOT NULL,
    StatusID SMALLINT NOT NULL DEFAULT 0,
    Timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ModuleRole(
    RoleID TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS ReactionRole(
    MessageID TEXT NOT NULL,
    Emoji TEXT NOT NULL,
    RoleID TEXT NOT NULL,
    PRIMARY KEY (MessageID, Emoji)
);

CREATE TABLE IF NOT EXISTS ReactionRoleUniquenessGroup(
    MessageID TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS MemberWarning(
    ID INTEGER PRIMARY KEY,
    UserID TEXT NOT NULL,
    Timestamp TEXT NOT NULL,
    Reason TEXT
);

CREATE TABLE IF NOT EXISTS GroupRequest(
    ID INTEGER PRIMARY KEY,
    UserId TEXT NOT NULL,
    Course TEXT NOT NULL,
    GroupNr INTEGER NOT NULL,
    UNIQUE (UserId, Course, GroupNr)
);

CREATE TABLE IF NOT EXISTS GroupOffer(
    ID INTEGER PRIMARY KEY,
    UserId TEXT NOT NULL,
    Course TEXT NOT NULL,
    GroupNr INTEGER NOT NULL,
    MessageId TEXT,
    UNIQUE (UserId, Course)
);

CREATE TABLE IF NOT EXISTS BotOnlyChannel(
    ChannelID TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS MemberNameHistory(
    UserID TEXT NOT NULL,
    Name TEXT NOT NULL,
    Timestamp TEXT NOT NULL,
    PRIMARY KEY (UserID, Timestamp)
);

-- many-to-one: Many user reminders correspond to one reminder job via JobID
CREATE TABLE IF NOT EXISTS RemindmeJobs(
    JobID TEXT PRIMARY KEY,
    Timestamp Text NOT NULL,
    Message Text NOT NULL
);

CREATE TABLE IF NOT EXISTS RemindmeUserReminders(
    ID INTEGER PRIMARY KEY,
    JobID TEXT NOT NULL,
    UserID TEXT NOT NULL
);
