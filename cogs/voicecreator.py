import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from typing import Optional
from discord.ext.commands import FlagConverter, flag

class VoiceFlags(FlagConverter, case_insensitive=True):
    name: Optional[str] = flag(
        default=None,
        description="Name for the voice channel"
    )
    limit: int = flag(
        default=0,
        description="User limit (0 = unlimited)"
    )

class VoiceCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = {}  # {user_id: channel_id}
        self.config = getattr(bot, "config", {}).get("voice_creator", {})
        self.voice_cleanup.start()

    @tasks.loop(minutes=5)
    async def voice_cleanup(self):
        """Cleanup empty temporary channels"""
        for user_id, channel_id in list(self.active_channels.items()):
            channel = self.bot.get_channel(channel_id)
            if not channel or len(channel.members) == 0:
                try:
                    await channel.delete()
                    del self.active_channels[user_id]
                except discord.HTTPException:
                    pass

    @commands.hybrid_command()
    async def voice(self, ctx, *, flags: VoiceFlags):
        """Create a temporary voice channel"""
        # Prevent user from creating multiple channels
        if ctx.author.id in self.active_channels:
            existing_channel = self.bot.get_channel(self.active_channels[ctx.author.id])
            if existing_channel:
                return await ctx.send(f"❌ You already have an active voice channel: {existing_channel.mention}", delete_after=15)
            else:
                del self.active_channels[ctx.author.id]  # Cleanup stale entry

        # Ensure a valid name is set
        channel_name = flags.name.strip() if flags.name else f"{ctx.author.name}'s Channel"

        try:
            category = await self._get_category(ctx.guild)
            channel = await ctx.guild.create_voice_channel(
                name=channel_name,
                user_limit=flags.limit,
                category=category,
                reason=f"Temporary channel by {ctx.author}"
            )
            
            self.active_channels[ctx.author.id] = channel.id
            
            await ctx.send(
                f"✅ Created voice channel: {channel.mention}\n"
                f"**Name:** `{channel_name}` | **Limit:** `{flags.limit or 'Unlimited'}`",
                delete_after=30
            )

        except discord.HTTPException:
            await ctx.send("❌ Failed to create channel", delete_after=10)

    async def _get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        """Get or create the category for temporary channels"""
        category_id = self.config.get("category_id")
        if category_id:
            category = guild.get_channel(category_id)
            if category and isinstance(category, discord.CategoryChannel):
                return category
        return await guild.create_category("Temporary Channels")

async def setup(bot):
    await bot.add_cog(VoiceCreator(bot))
