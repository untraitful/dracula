"""Thin async sqlite wrapper used by every cog."""

from typing import Any, Iterable, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS prefixes (
    guild_id INTEGER PRIMARY KEY,
    prefix TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS greetings (
    guild_id INTEGER NOT NULL,
    kind TEXT NOT NULL,           -- welcome / goodbye / boost
    channel_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (guild_id, kind, channel_id)
);
CREATE TABLE IF NOT EXISTS autoroles (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS autoresponders (
    guild_id INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    response TEXT NOT NULL,
    PRIMARY KEY (guild_id, trigger)
);
CREATE TABLE IF NOT EXISTS reactionroles (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);
CREATE TABLE IF NOT EXISTS afk (
    user_id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL,
    since INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jail (
    guild_id INTEGER PRIMARY KEY,
    role_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jailed (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    roles TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS warns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS voicemaster (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS vm_channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS antinuke (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    threshold INTEGER NOT NULL DEFAULT 3,
    punishment TEXT NOT NULL DEFAULT 'ban'
);
CREATE TABLE IF NOT EXISTS embeds (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    script TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    created INTEGER NOT NULL,
    PRIMARY KEY (guild_id, name)
);
CREATE TABLE IF NOT EXISTS antinuke_whitelist (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def execute(self, query: str, *args: Any) -> int:
        cur = await self.conn.execute(query, args)
        await self.conn.commit()
        return cur.rowcount

    async def fetchone(self, query: str, *args: Any) -> Optional[aiosqlite.Row]:
        async with self.conn.execute(query, args) as cur:
            return await cur.fetchone()

    async def fetchall(self, query: str, *args: Any) -> Iterable[aiosqlite.Row]:
        async with self.conn.execute(query, args) as cur:
            return await cur.fetchall()

    async def fetchval(self, query: str, *args: Any) -> Any:
        row = await self.fetchone(query, *args)
        return row[0] if row else None
