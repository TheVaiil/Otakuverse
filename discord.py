import discord
from discord import app_commands
from discord.ext import commands
import yaml
import logging
import os
from pathlib import Path
import asyncio

# Optional: Use uvloop for improved performance on UNIX systems.
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logging.info("Using uvloop for improved performance.")
except ImportError:
    logging.info("uvloop not installed, using default asyncio event loop.")

# Constants
CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")
LOG_DIR = "logs"
COGS_DIR = "cogs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Ensure required directories exist
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(COGS_DIR).mkdir(parents=True, exist_ok=True)

# Set up logging with both console and file handlers
logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)

# Console handler for real-time logging output
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(stream_handler)

# File handler to persist logs to a file for later review
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

def load_config() -> dict:
    """
    Load configuration from a YAML file.

    The configuration file (default: config/config.yaml) should be in YAML format
    and must include at least the following key:
        - DISCORD_TOKEN: Your Discord bot's token.

    Returns:
        A dictionary containing configuration parameters.

    Raises:
        SystemExit: If the configuration file cannot be loaded or is missing required keys.
    """
    try:
        with open(CONFIG_PATH, "r") as file:
            config = yaml.safe_load(file)
            if config is None or "DISCORD_TOKEN" not in config:
                logger.error("Configuration file is empty or missing required keys (e.g., 'DISCORD_TOKEN').")
                raise SystemExit(1)
            return config
    except Exception as e:
        logger.error("Error loading config: %s", e)
        raise SystemExit(1)

config = load_config()

# Initialize bot with slash command capabilities
intents = discord.Intents.default()
intents.message_content = True

class SlashBot(commands.Bot):
    """
    A subclass of commands.Bot to initialize a bot with slash commands.
    """
    def __init__(self) -> None:
        # A dummy prefix is required but unused when using slash commands.
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None  # Disable the default help command
        )

    async def setup_hook(self) -> None:
        """
        Called before the bot connects to Discord.
        Loads all cog extensions and synchronizes the slash command tree.
        """
        await self.load_cogs()
        await self.tree.sync()

    async def load_cogs(self) -> None:
        """
        Dynamically load all cog extensions from the COGS directory.

        Each Python file (except __init__.py) in the cogs directory is treated as a cog.
        Errors during cog loading are logged with detailed information.
        """
        cog_path = Path(COGS_DIR)
        for file in cog_path.glob("*.py"):
            if file.stem == "__init__":
                continue
            cog_name = file.stem
            try:
                await self.load_extension(f"{COGS_DIR}.{cog_name}")
                logger.info("Successfully loaded cog: %s", cog_name)
            except Exception as e:
                logger.error("Failed to load cog %s: %s", cog_name, e, exc_info=True)

bot = SlashBot()

@bot.event
async def on_ready() -> None:
    """
    Event handler called when the bot is ready.
    Logs the bot's username and ID.
    """
    logger.info("Bot initialized as %s (ID: %d)", bot.user.name, bot.user.id)
    print(f"Logged in as {bot.user}!")

@bot.tree.command(name="greet", description="Send a greeting")
async def greet(interaction: discord.Interaction) -> None:
    """
    Slash command to send a greeting to the user.

    Args:
        interaction (discord.Interaction): The interaction object representing the command invocation.
    """
    await interaction.response.send_message(f"Hello {interaction.user.mention}! Ready to help.")

@bot.tree.command(name="reload_cog", description="Reload a specific cog (owner only)")
async def reload_cog(interaction: discord.Interaction, cog: str) -> None:
    """
    Slash command to reload a specific cog extension.
    Only the bot owner is permitted to execute this command.

    Args:
        interaction (discord.Interaction): The interaction object representing the command invocation.
        cog (str): The name of the cog (without the .py extension) to reload.
    """
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
        return
    
    cog_extension = f"{COGS_DIR}.{cog}"
    try:
        await bot.reload_extension(cog_extension)
        await bot.tree.sync()
        await interaction.response.send_message(f"Successfully reloaded cog: {cog}", ephemeral=True)
    except Exception as e:
        logger.error("Failed to reload cog %s: %s", cog, e, exc_info=True)
        await interaction.response.send_message(f"Failed to reload cog: {e}", ephemeral=True)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    """
    Global error handler for slash commands.
    Logs the error and sends a generic error message to the user.

    Args:
        interaction (discord.Interaction): The interaction object that triggered the error.
        error (app_commands.AppCommandError): The error that occurred.
    """
    logger.error("Slash command error: %s", error, exc_info=True)
    if interaction.response.is_done():
        await interaction.followup.send("An error occurred while processing your command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred while processing your command.", ephemeral=True)

async def main() -> None:
    """
    Main entry point for running the bot.

    Retrieves the Discord token from the configuration and starts the bot.
    Handles keyboard interrupts and ensures the bot is properly shut down..
    """
    try:
        discord_token = config.get("DISCORD_TOKEN")
        if not discord_token:
            logger.critical("Missing DISCORD_TOKEN in configuration")
            raise SystemExit(1)
        await bot.start(discord_token)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
