import discord
from discord.ext import commands
import time
import platform
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

class UptimeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()
        self.stats_cache: Dict[str, Tuple[float, object]] = {
            'guilds': (0, 0),
            'users': (0, 0)
        }
        self.cache_timeout = 30  # Seconds

    def get_bot_uptime(self) -> str:
        """Returns formatted uptime string without zero values"""
        delta = timedelta(seconds=int(time.time() - self.start_time))
        parts = []
        
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days: parts.append(f"{days}d")
        if hours: parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        if seconds: parts.append(f"{seconds}s")
        
        return " ".join(parts) or "0s"

    async def get_cached_stats(self, key: str, func: callable) -> int:
        """Cache expensive stats calculations"""
        now = time.time()
        cached_time, value = self.stats_cache[key]
        
        if now - cached_time < self.cache_timeout:
            return value
            
        new_value = await self.bot.loop.run_in_executor(None, func)
        self.stats_cache[key] = (now, new_value)
        return new_value

    @commands.command(name="uptime", help="Shows the bot's current uptime and system stats")
    async def uptime_command(self, ctx: commands.Context):
        """Improved uptime command with better error handling"""
        try:
            # Get stats with caching
            total_guilds = len(self.bot.guilds)
            total_users = sum(g.member_count or 0 for g in self.bot.guilds)

            embed = discord.Embed(
                title=f"{self.bot.user.name} Status",
                color=discord.Color.green()
            )
            
            # Uptime section
            embed.add_field(
                name="🕒 Uptime",
                value=f"```{self.get_bot_uptime()}```",
                inline=False
            )
            
            # Bot stats
            bot_stats = [
                f"Servers: {total_guilds}",
                f"Users: {total_users}",
                f"Shards: {self.bot.shard_count or 1}",
                f"Latency: {self.bot.latency*1000:.2f}ms"
            ]
            embed.add_field(
                name="🤖 Bot Stats",
                value="```" + "\n".join(bot_stats) + "```",
                inline=True
            )
            
            # System stats
            system_stats = [
                f"Python: {platform.python_version()}",
                f"discord.py: {discord.__version__}",
                f"OS: {platform.system()} {platform.release()}"
            ]
            
            if PSUTIL_AVAILABLE:
                try:
                    process = psutil.Process()
                    with process.oneshot():
                        cpu = psutil.cpu_percent(interval=None)
                        mem = process.memory_info().rss / 1024**2
                        
                    system_stats.extend([
                        f"CPU: {cpu:.1f}%",
                        f"Memory: {mem:.2f} MB"
                    ])
                except Exception as e:
                    system_stats.append("[Resource stats unavailable]")

            embed.add_field(
                name="💻 System Stats",
                value="```" + "\n".join(system_stats) + "```",
                inline=True
            )

            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send("❌ Failed to retrieve uptime stats")
            self.bot.logger.error(f"Uptime command error: {str(e)}")

async def setup(bot: commands.Bot):
    await bot.add_cog(UptimeCog(bot))