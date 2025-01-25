import discord
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="commands")
    async def show_commands(self, ctx):
        """Displays a list of all available commands."""
        embed = discord.Embed(
            title="Bot Commands",
            description="Here is a list of all the commands you can use:",
            color=discord.Color.blue()
        )

        for cog_name, cog in self.bot.cogs.items():
            command_list = "\n".join([f"**!{command.name}**: {command.help}" for command in cog.get_commands() if command.help])
            if command_list:
                embed.add_field(name=cog_name, value=command_list, inline=False)

        embed.set_footer(text="Use !command for more details about each command.")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Help(bot))
