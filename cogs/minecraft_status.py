import discord
from discord.ext import commands
from discord import app_commands
from mcstatus import JavaServer

class MinecraftStatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Replace these with your actual server details
        self.server_ip = "51.77.35.232"
        self.server_port = 25565  # Default Minecraft port

    @app_commands.command(name="mcstatus", description="Check Minecraft server online status")
    async def mcstatus(self, interaction: discord.Interaction):
        await interaction.response.defer()
        server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")

        try:
            status = server.status()
            embed = discord.Embed(
                title=f"🟢 Server Online",
                description=f"Your Minecraft server is online and running smoothly!",
                color=discord.Color.green()
            )
            embed.add_field(name="🌐 IP Address", value=f"`{self.server_ip}:{self.server_port}`", inline=False)
            embed.add_field(name="👥 Players Online", value=f"**{status.players.online} / {status.players.max}**", inline=True)
            embed.add_field(name="📌 Version", value=f"`{status.version.name}`", inline=True)
            embed.set_footer(text="✅ Server is up and running")

        except Exception as e:
            embed = discord.Embed(
                title="🔴 Server Offline",
                description=f"It seems your Minecraft server isn't reachable at the moment.",
                color=discord.Color.red()
            )
            embed.add_field(name="🌐 IP Address", value=f"`{self.server_ip}:{self.server_port}`", inline=False)
            embed.set_footer(text="⚠️ Server currently offline")

        await interaction.followup.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.tree.sync()
        print("MinecraftStatusCog Slash Commands Synced")

async def setup(bot):
    await bot.add_cog(MinecraftStatusCog(bot))
