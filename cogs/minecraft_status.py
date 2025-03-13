import discord
from discord.ext import commands
from mcstatus import JavaServer

class MinecraftStatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Replace these with your actual server details
        self.server_ip = "51.77.35.232"
        self.server_port = 25565  # Default Minecraft port

    @commands.command(name="mcstatus", help="Check if the Minecraft server is online.")
    async def mcstatus(self, ctx):
        server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")

        try:
            status = server.status()
            embed = discord.Embed(
                title="✅ Server Online!",
                color=discord.Color.green()
            )
            embed.add_field(name="IP Address", value=self.server_ip, inline=False)
            embed.add_field(name="Players Online", value=f"{status.players.online}/{status.players.max}", inline=True)
            embed.add_field(name="Version", value=status.version.name, inline=True)
            embed.set_footer(text="Minecraft Server Status")
        except Exception as e:
            embed = discord.Embed(
                title="❌ Server Offline!",
                description=f"Server `{self.server_ip}` appears to be offline.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Minecraft Server Status")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MinecraftStatusCog(bot))
