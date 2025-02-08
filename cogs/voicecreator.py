import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from typing import Optional  # Added missing import

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
    @app_commands.describe(name="Channel name", limit="User limit (0 for unlimited)")
    async def voice(self, ctx, name: str = "Custom Voice", limit: int = 0):
        """Create a temporary voice channel"""
        category = await self._get_category(ctx.guild)
        
        try:
            channel = await ctx.guild.create_voice_channel(
                name=name,
                user_limit=limit,
                category=category,
                reason=f"Temporary channel by {ctx.author}"
            )
            
            self.active_channels[channel.id] = {
                "owner": ctx.author.id,
                "created_at": discord.utils.utcnow()
            }
            
            await ctx.send(f"🎧 Voice channel created: {channel.mention}", delete_after=30)
            
        except discord.HTTPException as e:
            await ctx.send("❌ Failed to create channel", delete_after=10)

    async def _get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        category_id = self.config.get("category_id")
        if category_id:
            return guild.get_channel(category_id)
        
        # Create category if not exists
        return await guild.create_category("Temporary Channels")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle private channel permissions"""
        if after.channel and after.channel.id in self.active_channels:
            channel_data = self.active_channels[after.channel.id]
            if channel_data["owner"] == member.id:
                await after.channel.set_permissions(
                    member, 
                    manage_channels=True,
                    move_members=True
                )

async def setup(bot):
    await bot.add_cog(VoiceCreator(bot))