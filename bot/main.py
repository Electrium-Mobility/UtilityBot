import logging
from dotenv import load_dotenv
import discord
from discord.ext import commands

from bot.core.logging import setup_logging
from bot.core.loader import load_feature_extensions
from bot.config import settings

import os
import asyncio

def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    return bot


async def main_async():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    logger = logging.getLogger("utilitybot")
    

    bot = create_bot()

    @bot.event
    async def on_ready():
        logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Load all feature module extensions
    await load_feature_extensions(bot)

    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        logger.error("DISCORD_TOKEN is not set. Please configure it in .env.")
        return

    await bot.start(token)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()