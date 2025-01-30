import discord
from discord.ext import commands
import yaml
import logging
import os
from pathlib import Path
import asyncio
from aiocache import Cache
import traceback
from typing import Any, Callable, Awaitable

# Constants
CONFIG_PATH = "config/config.yaml"
LOG_DIR = "logs"
BOT_LOG_FILE = os.path.join(LOG_DIR, "bot.log")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "error.log")
COGS_DIR = "cogs"

# Ensure directories exist
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(COGS_DIR).mkdir(parents=True, exist_ok=True)

# Basic logging setup for initial config loading errors
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
pre_logger = logging.getLogger("discord_bot_pre")

def load_config() -> dict:
    """Load configuration from YAML file."""
    try:
        with open(CONFIG_PATH, "r") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        pre_logger.error("Config file not found at %s", CONFIG_PATH)
        raise SystemExit(1)
    except yaml.YAMLError as e:
        pre_logger.error("Error parsing config file: %s", e)
        raise SystemExit(1)

config = load_config()

def setup_logging() -> logging.Logger:
    """Configure logging handlers and formatters."""
    logger = logging.getLogger("discord_bot")
    logger.setLevel(getattr(logging, config.get("LOG_LEVEL", "INFO").upper()))
    
    # Clear existing handlers to prevent duplicates during reloads
    if logger.handlers:
        for handler in logger.handlers:
            logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Regular File Handler
    file_handler = logging.FileHandler(BOT_LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Error-specific File Handler
    error_handler = logging.FileHandler(ERROR_LOG_FILE)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger

logger = setup_logging()

# Initialize bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=config.get("COMMAND_PREFIX", "!"),
    intents=intents,
    help_command=None  # Consider implementing custom help command
)

# Cache setup
cache = Cache(Cache.MEMORY)

async def get_or_set_cache(key: str, func: Callable[[], Awaitable[Any]], ttl: int = 300) -> Any:
    """Retrieve value from cache or set it using provided async function."""
    value = await cache.get(key)
    if value is None:
        value = await func()
        await cache.set(key, value, ttl=ttl)
    return value

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Global error handler for commands with improved traceback logging."""
    user_friendly_messages = {
        commands.CommandOnCooldown: lambda e: f"This command is cooling down. Try again in {e.retry_after:.1f}s.",
        commands.MissingRequiredArgument: "Missing required argument. Check command usage.",
        commands.CommandNotFound: "Command not found. Use !help for available commands.",
        commands.MissingPermissions: lambda e: f"Required permissions: {', '.join(e.missing_permissions)}",
        commands.NotOwner: "This command is restricted to the bot owner.",
        commands.MissingRole: lambda e: f"Required role: {e.missing_role}",
        commands.MissingAnyRole: lambda e: f"Requires one of: {', '.join(e.missing_roles)}"
    }

    for error_type, message in user_friendly_messages.items():
        if isinstance(error, error_type):
            response = message(error) if callable(message) else message
            await ctx.send(response)
            logger.warning("Command error handled: %s", error)
            return

    logger.error("Unhandled command error occurred", exc_info=error)
    await ctx.send("An unexpected error occurred. Please try again later.")

@bot.command()
@commands.cooldown(rate=2, per=10, type=commands.BucketType.user)
async def greet(ctx: commands.Context) -> None:
    """Send a greeting with cooldown management."""
    await ctx.send(f"Hello {ctx.author.mention}! Ready to help.")

async def load_cogs() -> None:
    """Dynamically load all cogs from the COGS directory."""
    cog_path = Path(COGS_DIR)
    for file in cog_path.glob("*.py"):
        if file.stem == "__init__":
            continue
            
        cog_name = file.stem
        try:
            await bot.load_extension(f"{COGS_DIR}.{cog_name}")
            logger.info("Successfully loaded cog: %s", cog_name)
        except Exception as e:
            logger.error("Failed to load cog %s: %s", cog_name, e, exc_info=True)

@bot.command()
@commands.is_owner()
async def reload_cog(ctx: commands.Context, cog: str) -> None:
    """Reload a specific cog with better error handling."""
    cog_extension = f"{COGS_DIR}.{cog}"
    
    try:
        await bot.unload_extension(cog_extension)
    except commands.ExtensionNotLoaded:
        pass  # Cog wasn't loaded, proceed to load
    except Exception as e:
        logger.error("Failed to unload cog %s: %s", cog, e, exc_info=True)
        await ctx.send(f"Failed to unload cog: {e}")
        return

    try:
        await bot.load_extension(cog_extension)
        await ctx.send(f"Successfully reloaded cog: {cog}")
        logger.info("Reloaded cog: %s", cog)
    except Exception as e:
        logger.error("Failed to load cog %s: %s", cog, e, exc_info=True)
        await ctx.send(f"Failed to reload cog: {e}")

@bot.event
async def on_ready() -> None:
    """Handle startup completion with proper logging."""
    logger.info("Bot initialized as %s (ID: %d)", bot.user.name, bot.user.id)
    print(f"Logged in as {bot.user}!\nSuccessfully startup status!")  # BisectHosting requirement

async def main() -> None:
    """Main entry point with improved resource management."""
    if "DISCORD_TOKEN" not in config:
        logger.critical("Missing DISCORD_TOKEN in configuration")
        raise SystemExit(1)

    try:
        async with bot:
            await load_cogs()
            await bot.start(config["DISCORD_TOKEN"])
    except KeyboardInterrupt:
        logger.info("Bot shutdown initiated by keyboard interrupt")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
    finally:
        logger.info("Closing resources...")
        await cache.close()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())