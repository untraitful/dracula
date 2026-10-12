import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from core.bot import Dracula, load_owner_ids


async def main():
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN is not set (copy .env.example to .env and fill it in)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    async with Dracula(owner_ids=load_owner_ids(), db_path=os.getenv("DATABASE_PATH", "dracula.db")) as bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
