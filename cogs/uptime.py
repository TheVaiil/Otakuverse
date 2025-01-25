import discord
from discord.ext import commands
import time
import platform

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

class UptimeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    def get_bot_uptime(self) -> str:
        now = time.time()
        diff = int(now - self.start_time)

        days = diff // 86400
        hours = (diff % 86400) // 3600
        minutes = (diff % 3600) // 60
        seconds = diff % 60

        uptime_parts = []
        if days > 0:
            uptime_parts.append(f"{days}d")
        if hours > 0:
            uptime_parts.append(f"{hours}h")
        if minutes > 0:
            uptime_parts.append(f"{minutes}m")
        if seconds > 0:
            uptime_parts.append(f"{seconds}s")

        return " ".join(uptime_parts) if uptime_parts else "0s"

    @commands.command(name="uptime", help="Shows the bot's current uptime and some stats.")
    async def uptime_command(self, ctx: commands.Context):
        uptime_str = self.get_bot_uptime()

        # Might be incomplete if you lack member intents
        py_version = platform.python_version()
        dpy_version = discord.__version__

        embed = discord.Embed(
            title="Bot Uptime & Stats",
            color=discord.Color.green()
        )
        embed.add_field(name="Uptime", value=uptime_str, inline=False)
        embed.add_field(name="Servers", value=str(total_guilds), inline=True)
        embed.add_field(name="Users (approx.)", value=str(total_users), inline=True)
        embed.add_field(name="Python", value=py_version, inline=True)
        embed.add_field(name="discord.py", value=dpy_version, inline=True)

        # Optional system resources if psutil is installed
        if PSUTIL_AVAILABLE:
            process = psutil.Process()
            with process.oneshot():
                cpu_usage = psutil.cpu_percent(interval=None)
                mem_info = process.memory_info()
                mem_usage_mb = mem_info.rss / 1024 ** 2

            embed.add_field(name="CPU Usage (%)", value=f"{cpu_usage:.2f}%", inline=True)
            embed.add_field(name="Memory Usage (MB)", value=f"{mem_usage_mb:.2f} MB", inline=True)
        else:
            embed.add_field(
                name="CPU/Memory Stats",
                value="Install `psutil` for resource usage info.",
                inline=False
            )

        embed.set_footer(text="Uptime command")
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(UptimeCog(bot))
