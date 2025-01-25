import discord
from discord.ext import commands
import yaml
import logging
import os
from pathlib import Path
import asyncio
from aiocache import Cache

import traceback  # For detailed error logging

# Constants
CONFIG_PATH = "config/config.yaml"
LOG_DIR = "logs"
BOT_LOG_FILE = os.path.join(LOG_DIR, "bot.log")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "error.log")
COGS_DIR = "cogs"

# Ensure the logs directory exists
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(COGS_DIR).mkdir(parents=True, exist_ok=True)

# Load configuration
def load_config():
    with open(CONFIG_PATH, "r") as file:
        return yaml.safe_load(file)

config = load_config()

# Setup Logging
def setup_logging():
    logger = logging.getLogger("discord_bot")
    logger.setLevel(getattr(logging, config.get("LOG_LEVEL", "INFO").upper()))

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler for general logs
    file_handler = logging.FileHandler(BOT_LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # File Handler for error logs
    error_handler = logging.FileHandler(ERROR_LOG_FILE)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger

logger = setup_logging()

# Initialize bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True  # Enable if your bot needs to read message content
intents.voice_states = True
bot = commands.Bot(command_prefix=config.get("COMMAND_PREFIX", "!"), intents=intents)

# Cache setup
cache = Cache(Cache.MEMORY)

# Helper function to cache responses
async def get_or_set_cache(key, func, ttl=300):
    value = await cache.get(key)
    if value is None:
        value = await func()
        await cache.set(key, value, ttl=ttl)
    return value

# Improved Error Handling
@bot.event
async def on_command_error(ctx, error):
    """
    Global error handler for commands. Catches common discord.py exceptions
    and provides more user-friendly messages. Logs unhandled exceptions.
    """
    if isinstance(error, commands.CommandOnCooldown):
        # Provide a friendlier cooldown message, e.g., multiple uses allowed
        await ctx.send(
            f"This command is on cooldown. Try again in {round(error.retry_after, 2)} seconds."
        )
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("You are missing a required argument. Please check the command usage.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("That command does not exist. Use `!help` to see available commands.")
    elif isinstance(error, commands.MissingPermissions):
        missing_perms = ', '.join(error.missing_permissions)
        await ctx.send(f"You do not have the required permissions: **{missing_perms}**.")
    elif isinstance(error, commands.NotOwner):
        await ctx.send("Only the bot owner can use this command.")
    elif isinstance(error, commands.MissingRole):
        await ctx.send(f"You need the **{error.missing_role}** role to use this command.")
    elif isinstance(error, commands.MissingAnyRole):
        missing_roles = ', '.join(error.missing_roles)
        await ctx.send(f"You need at least one of the following roles: **{missing_roles}**.")
    else:
        # Log the full traceback for unhandled errors
        logger.error("Unhandled exception: %s\n%s", error, traceback.format_exc())
        await ctx.send("An unexpected error occurred. Please try again later.")

# Example command with rate limiting (2 uses per 10 seconds)
@bot.command()
@commands.cooldown(rate=2, per=10, type=commands.BucketType.user)
async def greet(ctx):
    """Send a greeting message with a simple cooldown."""
    await ctx.send(f"Hello, {ctx.author.name}! How can I assist you today?")

# Async file reading example
async def async_read_file(file_path):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, Path(file_path).read_text)

# Example of handling large tasks with asyncio.gather
async def handle_large_task():
    async def sub_task(task_id):
        await asyncio.sleep(1)  # Simulate a time-consuming task
        return f"Task {task_id} completed"

    tasks = [sub_task(i) for i in range(10)]  # Simulate 10 concurrent tasks
    results = await asyncio.gather(*tasks)
    return results

@bot.command()
async def tasks(ctx):
    """Run multiple tasks concurrently."""
    results = await handle_large_task()
    await ctx.send(f"Tasks completed: {', '.join(results)}")

# Graceful shutdown
@bot.event
async def on_shutdown():
    logger.info("Bot is shutting down...")
    await cache.close()

# Load Cogs dynamically
async def load_cogs():
    for filename in os.listdir(COGS_DIR):
        # Skip __init__.py and ensure only .py files are loaded
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = filename[:-3]  # Remove .py extension
            try:
                await bot.load_extension(f"cogs.{cog_name}")
                logger.info(f"Loaded cog: {cog_name}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog_name}: {e}")

# Reload Cog Command
@bot.command()
@commands.is_owner()
async def reload_cog(ctx, cog: str):
    """Reload a specific cog."""
    try:
        await bot.unload_extension(f"cogs.{cog}")
        await bot.load_extension(f"cogs.{cog}")
        await ctx.send(f"Reloaded cog: {cog}")
        logger.info(f"Reloaded cog: {cog}")
    except Exception as e:
        await ctx.send(f"Failed to reload cog: {cog}\n{e}")
        logger.error(f"Failed to reload cog {cog}: {e}")

# BisectHosting knows the bot is online       
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    print("Successfully startup status!")  # Required for BisectHosting panel

# Run the bot
if __name__ == "__main__":
    async def main():
        try:
            async with bot:
                await load_cogs()
                await bot.start(config["DISCORD_TOKEN"])
        except asyncio.CancelledError:
            logger.warning("Bot was interrupted. Shutting down...")
        except KeyboardInterrupt:
            logger.info("Bot terminated manually. Cleaning up...")
        except Exception as e:
            logger.error("An unexpected error occurred: %s\n%s", e, traceback.format_exc())
        finally:
            await bot.close()
            logger.info("Bot has shut down.")

    asyncio.run(main())
