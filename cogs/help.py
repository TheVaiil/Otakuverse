import discord
from discord.ext import commands

class AdvancedHelp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="helpme")
    async def show_help(self, ctx, *, command_name=None):
        """Displays a detailed help menu for all commands or a specific command."""
        # Delete the command message to keep the channel clean
        await ctx.message.delete()

        if command_name:
            command = self.bot.get_command(command_name)
            if command:
                if not self._can_access_command(ctx, command):
                    await ctx.author.send("You don't have permission to view this command.")
                    return
                embed = self._generate_command_embed(command)
                await ctx.author.send(embed=embed)
            else:
                await ctx.author.send(f"Command `{command_name}` not found.")
        else:
            embed = self._generate_all_commands_embed(ctx)
            await ctx.author.send(embed=embed)

    def _generate_all_commands_embed(self, ctx):
        """Generates an embed for all available commands."""
        embed = discord.Embed(
            title="Help - Available Commands",
            description="Use `!helpme <command>` to get detailed information about a specific command.",
            color=discord.Color.blue()
        )

        for cog_name, cog in self.bot.cogs.items():
            command_list = "\n".join([
                f"**`!{command.name}`** - {command.help}"
                for command in cog.get_commands()
                if command.help and self._can_access_command(ctx, command)
            ])
            if command_list:
                embed.add_field(name=cog_name, value=command_list, inline=False)

        embed.set_footer(text="Use !helpme <command> for more details about each command.")
        return embed

    def _generate_command_embed(self, command):
        """Generates an embed for a specific command."""
        embed = discord.Embed(
            title=f"Help - {command.name}",
            description=command.help or "No description provided.",
            color=discord.Color.green()
        )

        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(command.aliases), inline=False)

        if command.usage:
            embed.add_field(name="Usage", value=f"`!{command.name} {command.usage}`", inline=False)
        else:
            embed.add_field(name="Usage", value=f"`!{command.name}`", inline=False)

        embed.set_footer(text="<> indicates required arguments, [] indicates optional arguments.")
        return embed

    def _can_access_command(self, ctx, command):
        """Checks if the user has access to a command based on their roles."""
        # Define staff roles that can access restricted commands
        staff_roles = {"Admin", "discord moderator", "Staff"}
        user_roles = {role.name for role in ctx.author.roles}

        # If the command is in a restricted cog (e.g., AIAutoMod), limit access
        if command.cog_name == "AIAutoMod":
            return bool(staff_roles & user_roles)  # User must have at least one staff role

        return True  # Allow access to all other commands

async def setup(bot):
    await bot.add_cog(AdvancedHelp(bot))
