import discord
from discord.ext import commands
from discord import app_commands

# This is the View that holds the dropdown menu
class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=180)  # The view will be disabled after 180 seconds of inactivity
        self.bot = bot
        # Add the dropdown to the view
        self.add_item(HelpDropdown(self.bot))

# This is the dropdown menu itself
class HelpDropdown(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Create a list of options for the dropdown
        # It dynamically finds all cogs and lists them
        options = [
            discord.SelectOption(label="Home", description="Return to the main help menu.", emoji="🏠")
        ]
        
        for cog_name, cog in bot.cogs.items():
            # Hide this HelpCog itself from the list
            if cog_name == "Help":
                continue
            # Only add the cog if it has application commands
            if cog.get_app_commands():
                options.append(discord.SelectOption(
                    label=cog_name,
                    description=cog.description or "Click to see commands.",
                    emoji="🧩" # You can assign emojis to your cogs
                ))
        
        super().__init__(
            placeholder="Select a category to see its commands...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        """This function is called when a user selects an option from the dropdown."""
        
        # The selected option's label (e.g., "General", "Moderation")
        selected_cog_name = self.values[0]
        
        # If the user selects "Home"
        if selected_cog_name == "Home":
            await interaction.response.edit_message(embed=HelpCog.create_main_embed(self.bot))
            return
            
        # Get the actual cog object from the bot
        cog = self.bot.get_cog(selected_cog_name)
        if not cog:
            # This should ideally not happen if the dropdown is generated correctly
            await interaction.response.edit_message(content="Error: Could not find this category.", embed=None)
            return

        # Create a new embed for the selected cog
        embed = discord.Embed(
            title=f"🧩 {cog.qualified_name} Commands",
            description=cog.description or "Here are the available commands in this category.",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Use /help <command> for more info on a command.")

        # Add a field for each command in the cog
        for command in cog.get_app_commands():
            embed.add_field(
                name=f"`/{command.name}`",
                value=command.description or "No description provided.",
                inline=False
            )
        
        # Edit the original message with the new embed
        await interaction.response.edit_message(embed=embed)


# The main Cog class
class Help(commands.Cog):
    """
    The central help command that displays all available commands.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def create_main_embed(bot: commands.Bot):
        """Creates the initial 'home' embed for the help command."""
        embed = discord.Embed(
            title="Help Menu",
            description=(
                f"Welcome to the help menu for **{bot.user.name}**!\n"
                "Please select a category from the dropdown below to see its commands."
            ),
            color=discord.Color.dark_embed()
        )
        embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
        embed.set_footer(text="This bot is powered by slash commands.")
        return embed

    @app_commands.command(name="help", description="Displays a list of all available commands.")
    async def help_command(self, interaction: discord.Interaction):
        """The main slash command for help."""
        embed = self.create_main_embed(self.bot)
        view = HelpView(self.bot)
        # Send the initial message with the dropdown. `ephemeral=True` makes it only visible to the user.
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))