import os
import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal

# This is a custom check to ensure only the bot owner can use these commands.
# It references the owner_ids from your config.json that are loaded in main.py
def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id not in interaction.client.owner_ids:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class Tools(commands.Cog):
    """
    Developer tools for managing the bot.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Command: Sync ---
    @app_commands.command(name="sync", description="Syncs slash commands with Discord.")
    @is_owner()
    async def sync(self, interaction: discord.Interaction, scope: Literal["global", "guild"]):
        """Syncs slash commands globally or to the current guild."""
        await interaction.response.defer(ephemeral=True)

        if scope == "guild":
            synced = await self.bot.tree.sync(guild=interaction.guild)
        else: # scope == "global"
            synced = await self.bot.tree.sync()

        await interaction.followup.send(
            f"Synced {len(synced)} commands {scope}ly."
        )
        print(f"Synced {len(synced)} commands {scope}ly.")


    # --- Command: Reload ---
    @app_commands.command(name="reload", description="Reloads a cog to apply code changes.")
    @is_owner()
    async def reload(self, interaction: discord.Interaction, cog: str):
        """Reloads a specific cog or all cogs."""
        await interaction.response.defer(ephemeral=True)
        
        if cog.lower() == 'all':
            reloaded_cogs = []
            failed_cogs = []
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py'):
                    cog_name = f"cogs.{filename[:-3]}"
                    try:
                        await self.bot.reload_extension(cog_name)
                        reloaded_cogs.append(cog_name)
                    except Exception as e:
                        failed_cogs.append(f"{cog_name} ({e})")
            
            response_message = ""
            if reloaded_cogs:
                response_message += f"Successfully reloaded: `{'`, `'.join(reloaded_cogs)}`\n"
            if failed_cogs:
                response_message += f"Failed to reload: `{'`, `'.join(failed_cogs)}`"
                
            await interaction.followup.send(response_message)
            print(f"--- Reloaded All Cogs ---")
            print(f"Success: {len(reloaded_cogs)} | Failed: {len(failed_cogs)}")
            print("-------------------------")

        else:
            cog_name = f"cogs.{cog.lower()}"
            try:
                await self.bot.reload_extension(cog_name)
                await interaction.followup.send(f"Successfully reloaded cog: `{cog_name}`")
                print(f"Reloaded cog: {cog_name}")
            except commands.ExtensionNotLoaded:
                await interaction.followup.send(f"Error: Cog `{cog_name}` is not loaded.")
            except commands.ExtensionNotFound:
                await interaction.followup.send(f"Error: Cog `{cog_name}` not found.")
            except Exception as e:
                await interaction.followup.send(f"An error occurred while reloading `{cog_name}`: \n```py\n{e}\n```")
                print(f"Failed to reload {cog_name}: {e}")

    @reload.autocomplete('cog')
    async def reload_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Provides autocomplete options for the reload command."""
        cogs = ['all'] + [filename[:-3] for filename in os.listdir('./cogs') if filename.endswith('.py')]
        return [
            app_commands.Choice(name=cog, value=cog)
            for cog in cogs if current.lower() in cog.lower()
        ]


    # --- Command: Clear Commands --- [NEW]
    @app_commands.command(name="clear-commands", description="Clears all slash commands and re-syncs.")
    @is_owner()
    async def clear_commands(self, interaction: discord.Interaction, scope: Literal["global", "guild"]):
        """Clears all slash commands from Discord and re-syncs the current ones."""
        await interaction.response.defer(ephemeral=True)

        if scope == "guild":
            # Clear commands for the current guild
            self.bot.tree.clear_commands(guild=interaction.guild)
            # Sync the empty list to the guild
            await self.bot.tree.sync(guild=interaction.guild)
            # Re-sync the actual commands from the code
            synced = await self.bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(
                f"Cleared all guild commands and re-synced {len(synced)} commands for this server."
            )
            print(f"Cleared and re-synced guild commands for {interaction.guild.name}.")
        
        else: # scope == "global"
            # Clear global commands
            self.bot.tree.clear_commands(guild=None)
            # Sync the empty list globally
            await self.bot.tree.sync(guild=None)
            # Re-sync the actual commands globally
            synced = await self.bot.tree.sync()
            await interaction.followup.send(
                f"Cleared all global commands and re-synced {len(synced)} commands."
            )
            print("Cleared and re-synced all global commands.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Tools(bot))