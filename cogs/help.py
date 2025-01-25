import discord
from discord.ext import commands

class AdvancedHelp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def show_help(self, ctx, *, command_name=None):
        """Displays a detailed help menu for all commands or a specific command."""
        if command_name:
            command = self.bot.get_command(command_name)
            if command:
                embed = self._generate_command_embed(command)
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"Command `{command_name}` not found.")
        else:
            embed = self._generate_all_commands_embed()
            await ctx.send(embed=embed)

    def _generate_all_commands_embed(self):
        """Generates an embed for all available commands."""
        embed = discord.Embed(
            title="Help - Available Commands",
            description="Use `!help <command>` to get detailed information about a specific command.",
            color=discord.Color.blue()
        )

        for cog_name, cog in self.bot.cogs.items():
            command_list = "\n".join([f"**`!{command.name}`** - {command.help}" for command in cog.get_commands() if command.help])
            if command_list:
                embed.add_field(name=cog_name, value=command_list, inline=False)

        embed.set_footer(text="Use !help <command> for more details about each command.")
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

async def setup(bot):
    await bot.add_cog(AdvancedHelp(bot))
