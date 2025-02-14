import discord
from discord import app_commands
from discord.ext import commands

class AdvancedHelp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="helpme", description="Show detailed help information")
    @app_commands.describe(command_name="Specific command to get help for")
    async def help_command(self, interaction: discord.Interaction, command_name: str = None):
        """Slash command for displaying help information"""
        if command_name:
            # Find specific command
            command = self.bot.tree.get_command(command_name)
            if command:
                if not self._can_access_command(interaction, command):
                    await interaction.response.send_message(
                        "⛔ You don't have permission to view this command.",
                        ephemeral=True
                    )
                    return
                
                embed = self._generate_command_embed(command)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"❌ Command `{command_name}` not found.",
                    ephemeral=True
                )
        else:
            # Show all available commands
            embed = self._generate_all_commands_embed(interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    def _generate_all_commands_embed(self, interaction: discord.Interaction) -> discord.Embed:
        """Generate embed showing all accessible commands"""
        embed = discord.Embed(
            title="📚 Bot Command Help",
            description="Use `/helpme [command]` for detailed command information",
            color=0x00ff00
        )

        # Organize commands by cog
        for cog_name, cog in self.bot.cogs.items():
            if cog_name == "AdvancedHelp":  # Skip help cog itself
                continue

            # Get slash commands from cog
            commands = cog.get_app_commands() if hasattr(cog, 'get_app_commands') else []
            accessible_commands = [
                f"• `/{cmd.name}` - {cmd.description}"
                for cmd in commands
                if self._can_access_command(interaction, cmd)
            ]

            if accessible_commands:
                embed.add_field(
                    name=f"**{cog_name}**",
                    value="\n".join(accessible_commands),
                    inline=False
                )

        embed.set_footer(text="🔒 Restricted commands require special permissions")
        return embed

    def _generate_command_embed(self, command: app_commands.Command) -> discord.Embed:
        """Generate detailed embed for a specific command"""
        embed = discord.Embed(
            title=f"📖 Command Help: /{command.name}",
            description=command.description or "No description available",
            color=0x0099ff
        )

        # Add parameters if any
        if command.parameters:
            params = []
            for param in command.parameters:
                required = "Required" if param.required else "Optional"
                param_info = f"`{param.name}` ({required})"
                if param.description:
                    param_info += f": {param.description}"
                params.append(param_info)
            
            embed.add_field(
                name="🔧 Parameters",
                value="\n".join(params) or "No parameters",
                inline=False
            )

        # Add permissions notice
        if self._is_restricted_command(command):
            embed.add_field(
                name="⚠️ Permissions",
                value="This command requires special privileges",
                inline=False
            )

        return embed

    def _can_access_command(self, interaction: discord.Interaction, command: app_commands.Command) -> bool:
        """Check if user has access to a command"""
        # Check for restricted cogs
        if self._is_restricted_command(command):
            return self._has_staff_role(interaction.user)
        return True

    def _is_restricted_command(self, command: app_commands.Command) -> bool:
        """Check if command belongs to a restricted cog"""
        if command.binding and command.binding.qualified_name == "AIAutoMod":
            return True
        return False

    def _has_staff_role(self, user: discord.Member) -> bool:
        """Check if user has staff role"""
        staff_roles = {"Admin", "Discord Moderator", "Staff"}
        return any(role.name in staff_roles for role in user.roles)

async def setup(bot):
    await bot.add_cog(AdvancedHelp(bot))