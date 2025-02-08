import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from typing import Optional
from discord.ext.commands import FlagConverter, flag  # Added FlagConverter

class VoiceFlags(FlagConverter):
    name: str = flag(
        default="Custom Voice",
        description="Name for the voice channel"
    )
    limit: int = flag(
        default=0,
        description="User limit (0 = unlimited)"
    )

class VoiceCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = {}
        self.config = getattr(bot, "config", {}).get("voice_creator", {})
        self.voice_cleanup.start()

    @tasks.loop(minutes=5)
    async def voice_cleanup(self):
        """Cleanup empty temporary channels"""
        for channel_id in list(self.active_channels.keys()):
            channel = self.bot.get_channel(channel_id)
            if not channel or len(channel.members) == 0:
                try:
                    await channel.delete()
                    del self.active_channels[channel_id]
                except:
                    pass

    @commands.hybrid_command()
    async def voice(self, ctx, flags: VoiceFlags):
        """Create a temporary voice channel"""
        try:
            category = await self._get_category(ctx.guild)
            channel = await ctx.guild.create_voice_channel(
                name=flags.name,
                user_limit=flags.limit,
                category=category,
                reason=f"Temporary channel by {ctx.author}"
            )
            
            self.active_channels[channel.id] = {
                "owner": ctx.author.id,
                "created_at": discord.utils.utcnow()
            }
            
            await ctx.send(
                f"🎧 Created voice channel: {channel.mention}\n"
                f"Name: `{flags.name}` | Limit: `{flags.limit or 'Unlimited'}`",
                delete_after=30
            )

        except discord.HTTPException:
            await ctx.send("❌ Failed to create channel", delete_after=10)

    async def _get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        category_id = self.config.get("category_id")
        if category_id:
            return guild.get_channel(category_id)
        return await guild.create_category("Temporary Channels")

  

async def setup(bot):
    await bot.add_cog(VoiceCreator(bot))