import os
import json
import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ADD THIS IMPORT AT THE TOP
from cogs.roles import UserRoleView 

# --- Bot Initialization ---

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Load configuration from config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

OWNER_IDS = config["owner_ids"]

# Setup logging
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

# Define intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        # Note: command_prefix is not needed for a slash-command-only bot
        super().__init__(
            command_prefix=" ", # A placeholder prefix is still required but will not be used
            intents=intents,
            owner_ids=set(OWNER_IDS)
        )
    
    # --- This entire setup_hook block is now INDENTED to be inside the class ---
    async def setup_hook(self):
        """This is called when the bot logs in."""
        
        # --- Cog Loading ---
        print("--- Loading Cogs ---")
        cogs_folder = Path("cogs")
        for file in cogs_folder.iterdir():
            if file.suffix == ".py":
                try:
                    await self.load_extension(f"cogs.{file.stem}")
                    print(f"Successfully loaded cog: {file.stem}")
                except Exception as e:
                    print(f"Failed to load cog {file.stem}: {e}")
        
        # --- Persistent Views ---
        print("--- Loading Persistent Views ---")
        try:
            with open('role_panels.json', 'r') as f:
                panels_data = json.load(f)
            
            for guild_id, data in panels_data.items():
                if "panel_message_id" in data:
                    # Create a new view instance
                    view = UserRoleView(self)
                    # Manually populate it with data for the specific guild
                    await view.populate_items(int(guild_id))
                    # Add the now-populated view to the bot
                    self.add_view(view, message_id=data["panel_message_id"])
                    print(f"Re-loaded persistent role view for guild {guild_id}")

        except FileNotFoundError:
            print("role_panels.json not found, skipping persistent view loading.")
        except json.JSONDecodeError:
            print("role_panels.json is empty or corrupted, skipping persistent view loading.")
        except Exception as e:
            print(f"Error loading persistent views: {e}")
            
        # --- Sync Application Commands ---
        print("--- Syncing Commands ---")
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} application commands.")
        except Exception as e:
            print(f"Failed to sync application commands: {e}")

    # --- This on_ready block is also INDENTED to be inside the class ---
    async def on_ready(self):
        """Called when the bot is ready and connected to Discord."""
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')
        await self.change_presence(activity=discord.Game(name=f"using /commands in {len(self.guilds)} servers"))


# The bot instance is created from the class
bot = MyBot()
# We add the launch_time attribute to the instance
bot.launch_time = discord.utils.utcnow()

# --- Global Slash Command Error Handler ---

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """A global error handler for all slash commands."""
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"This command is on cooldown. Please try again in {error.retry_after:.2f} seconds.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You do not have the required permissions to run this command.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            "You do not meet the requirements to use this command.",
            ephemeral=True
        )
    else:
        # Log the error for debugging
        print(f"An unhandled error occurred for command '{interaction.command.name}': {error}")
        
        # Inform the user
        if interaction.response.is_done():
            await interaction.followup.send("An unexpected error occurred. The developer has been notified.", ephemeral=True)
        else:
            await interaction.response.send_message("An unexpected error occurred. The developer has been notified.", ephemeral=True)
        
        # For deeper debugging, you can log the full traceback
        # import traceback
        # traceback.print_exception(type(error), error, error.__traceback__)


# --- Run the Bot ---

if __name__ == "__main__":
    if TOKEN is None:
        raise ValueError("DISCORD_TOKEN not found in .env file.")
    
    async def main():
        async with bot:
            await bot.start(TOKEN)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested. Cleaning up...")