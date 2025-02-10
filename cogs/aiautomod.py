import discord
from discord.ext import commands
import asyncio
import json
import openai
import yaml
import re
import time
import logging
import aiofiles
from collections import defaultdict, deque

def load_config():
    """
    Loads your config for the OpenAI API key and any other settings.
    """
    with open("config/config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# ============================== FILE-BASED STORAGE ==============================
class JsonDatabase:
    """
    Manages JSON file interactions for warnings, mutes, bans, and blacklisted words with async support.
    """
    def __init__(self, filename="data.json"):
        self.filename = filename
        self.data = asyncio.run(self.load_data())
        self.save_pending = False

    async def load_data(self):
        try:
            async with aiofiles.open(self.filename, "r", encoding="utf-8") as f:
                content = await f.read()
                return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"warnings": {}, "mutes": {}, "bans": {}, "blacklist": []}

    async def save_data(self):
        if not self.save_pending:
            self.save_pending = True
            await asyncio.sleep(2)  # Debounce frequent writes
            async with aiofiles.open(self.filename, "w", encoding="utf-8") as f:
                await f.write(json.dumps(self.data, indent=4))
            self.save_pending = False

    async def get_mute(self, user_id):
        return self.data["mutes"].get(str(user_id), 0)

    async def add_mute(self, user_id, duration):
        user_id = str(user_id)
        self.data["mutes"][user_id] = time.time() + duration
        await self.save_data()

    async def remove_mute(self, user_id):
        user_id = str(user_id)
        self.data["mutes"].pop(user_id, None)
        await self.save_data()

    async def get_ban(self, user_id):
        return self.data["bans"].get(str(user_id), 0)

    async def add_ban(self, user_id, duration):
        user_id = str(user_id)
        self.data["bans"][user_id] = time.time() + duration
        await self.save_data()

    async def remove_ban(self, user_id):
        user_id = str(user_id)
        self.data["bans"].pop(user_id, None)
        await self.save_data()

# ============================== MUTE SYSTEM ==============================
class MuteSystem:
    """
    Handles muting users temporarily with persistence.
    """
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    async def mute_user(self, ctx, member: discord.Member, duration: int):
        guild = ctx.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")

        if not mute_role:
            mute_role = await guild.create_role(name="Muted", reason="AutoMod Mute Role")
            for channel in guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        if mute_role in member.roles:
            await ctx.send(f"{member.mention} is already muted.")
            return

        await member.add_roles(mute_role)
        await self.db.add_mute(member.id, duration)
        await ctx.send(f"{member.mention} has been muted for {duration} seconds.")

        await asyncio.sleep(duration)
        if str(member.id) in self.db.data["mutes"]:  # Ensure mute still exists
            await member.remove_roles(mute_role)
            await self.db.remove_mute(member.id)
            await ctx.send(f"{member.mention} has been unmuted.")

# ============================== BAN SYSTEM ==============================
class BanSystem:
    """
    Handles banning users temporarily with persistence.
    """
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    async def ban_user(self, ctx, member: discord.Member, duration: int):
        await ctx.guild.ban(member, reason=f"Banned for {duration} seconds.")
        await self.db.add_ban(member.id, duration)
        await ctx.send(f"{member.mention} has been banned for {duration} seconds.")

        await asyncio.sleep(duration)
        if str(member.id) in self.db.data["bans"]:  # Ensure ban still exists
            await ctx.guild.unban(member)
            await self.db.remove_ban(member.id)
            await ctx.send(f"{member.mention} has been unbanned.")

# ============================== THE ACTUAL COG ==============================
class AIAutoMod(commands.Cog):
    """
    Main Cog that wires up the single on_message event.
    Also includes admin commands for blacklists, warnings, etc.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("AIAutoMod")
        config = load_config()
        self.db = JsonDatabase("data.json")  # JSON file-based storage
        self.mute_system = MuteSystem(bot, self.db)
        self.ban_system = BanSystem(bot, self.db)
        asyncio.run(self.db.load_data())
    
    @commands.command(name="mute")
    @commands.has_permissions(manage_roles=True)
    async def mute_command(self, ctx: commands.Context, member: discord.Member, duration: int):
        """Mutes a user temporarily."""
        await self.mute_system.mute_user(ctx, member, duration)

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban_command(self, ctx: commands.Context, member: discord.Member, duration: int):
        """Bans a user temporarily."""
        await self.ban_system.ban_user(ctx, member, duration)
    
async def setup(bot: commands.Bot):
    """Standard setup for dynamic loading."""
    await bot.add_cog(AIAutoMod(bot))
