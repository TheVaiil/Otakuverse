import discord
from discord import app_commands
from discord.ext import commands
import yaml
import logging
import os
from pathlib import Path
import asyncio

# Constants
CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")
LOG_DIR = "logs"
COGS_DIR = "cogs"

# Ensure directories exist
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(COGS_DIR).mkdir(parents=True, exist_ok=True)

# Basic logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("discord_bot")

def load_config() -> dict:
    """Load configuration from YAML file."""
    try:
        with open(CONFIG_PATH, "r") as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error("Error loading config: %s", e)
        raise SystemExit(1)

config = load_config()

# Initialize bot with slash commands
intents = discord.Intents.default()
intents.message_content = True

class SlashBot(commands.Bot):
    def __init__(self):
        # Fix: Use dummy prefix instead of None
        super().__init__(
            command_prefix="!",  # Required but unused prefix
            intents=intents,
            help_command=None    # Disable default help
        )

    async def setup_hook(self):
        await self.load_cogs()
        await self.tree.sync()

    async def load_cogs(self):
        """Dynamically load all cogs from the COGS directory."""
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
async def on_ready():
    logger.info("Bot initialized as %s (ID: %d)", bot.user.name, bot.user.id)
    print(f"Logged in as {bot.user}!")

@bot.tree.command(name="greet", description="Send a greeting")
async def greet(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello {interaction.user.mention}! Ready to help.")

@bot.tree.command(name="reload_cog", description="Reload a specific cog (owner only)")
async def reload_cog(interaction: discord.Interaction, cog: str):
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
        return
    
    cog_extension = f"{COGS_DIR}.{cog}"
    try:
        await bot.reload_extension(cog_extension)
        await bot.tree.sync()
        await interaction.response.send_message(f"Successfully reloaded cog: {cog}", ephemeral=True)
    except Exception as e:
        logger.error("Failed to reload cog %s: %s", cog, e)
        await interaction.response.send_message(f"Failed to reload cog: {e}", ephemeral=True)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error("Slash command error: %s", error, exc_info=True)
    if interaction.response.is_done():
        await interaction.followup.send("An error occurred while processing your command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred while processing your command.", ephemeral=True)

async def main():
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