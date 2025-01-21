"""
====================================================
Otakuverse Discord Bot
Copyright © 2025 Otakuverse Community
Developed for the Otakuverse Discord server by [vail]
====================================================

Description:
This bot is designed for the Otakuverse Discord server. It includes features such as:
1. Moderation tools (warnings, mutes, bans, etc.).
2. Random meme posting (Imgflip integration).
3. Scheduled meme posting.
4. Spam detection and management.
5. Uptime tracking.
6. Auto role assignment based on reactions.

This code is intended for use only by the Otakuverse community or with explicit permission.

====================================================
"""

import discord
from discord.ext import commands, tasks
from discord.utils import get
import requests
import sqlite3
import random
import asyncio
import logging
from datetime import datetime
import aiohttp
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not DISCORD_BOT_TOKEN:
    print("Error: DISCORD_BOT_TOKEN environment variable not set.")
    exit(1)

if not GITHUB_TOKEN:
    print("Error: GITHUB_TOKEN environment variable not set.")
    exit(1)

# Logging setup
logging.basicConfig(filename="moderation.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Intents and bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Enable message content intent
intents.reactions = True  # Enable reactions intent
bot = commands.Bot(command_prefix="!", intents=intents)

# Variables
WELCOME_CHANNEL_NAME = "welcome"
LOG_CHANNEL_NAME = "moderation-log"
DEFAULT_ROLE_NAME = "Member"
WARNING_LIMIT = 3
SPAM_THRESHOLD = 5
SPAM_TIME_LIMIT = 10
GITHUB_API_URL = "https://api.github.com/TheVaiil/Otakuverse/commits/main/"  # Replace with your GitHub repo details
CHANGELOG_CHANNEL_ID = 1330998006979498079  # Replace with your Discord changelog channel ID

# Uptime tracker
bot_start_time = datetime.utcnow()

# Temporary spam tracker
spam_tracker = {}

# Reaction roles storage
reaction_roles = {}

# Database initialization
def init_database():
    with sqlite3.connect('warnings.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                user_id INTEGER,
                guild_id INTEGER,
                warning_count INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS points (
                user_id INTEGER,
                guild_id INTEGER,
                points INTEGER
            )
        ''')

init_database()

# Reaction Role Commands
@bot.command()
@commands.has_permissions(manage_roles=True)
async def set_reaction_role(ctx, channel_id: int, message_id: int, emoji: str, role_name: str):
    """
    Assign a reaction to a role for a specific message.
    Usage: !set_reaction_role <channel_id> <message_id> <emoji> <role_name>
    """
    channel = bot.get_channel(channel_id)
    if not channel:
        await ctx.send("❌ Channel not found.")
        return

    message = await channel.fetch_message(message_id)
    if not message:
        await ctx.send("❌ Message not found.")
        return

    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role:
        await ctx.send("❌ Role not found.")
        return

    # Add to the reaction_roles dictionary
    if message_id not in reaction_roles:
        reaction_roles[message_id] = {}
    reaction_roles[message_id][emoji] = role.id

    # Add reaction to the message
    await message.add_reaction(emoji)

    await ctx.send(f"✅ Reaction role set: {emoji} -> {role.name}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id in reaction_roles:
        emoji = str(payload.emoji)
        if emoji in reaction_roles[payload.message_id]:
            guild = bot.get_guild(payload.guild_id)
            role_id = reaction_roles[payload.message_id][emoji]
            role = guild.get_role(role_id)
            if role:
                member = guild.get_member(payload.user_id)
                if member:
                    await member.add_roles(role)
                    channel = bot.get_channel(payload.channel_id)
                    if channel:
                        await channel.send(f"✅ {member.mention} has been given the {role.name} role.")

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.message_id in reaction_roles:
        emoji = str(payload.emoji)
        if emoji in reaction_roles[payload.message_id]:
            guild = bot.get_guild(payload.guild_id)
            role_id = reaction_roles[payload.message_id][emoji]
            role = guild.get_role(role_id)
            if role:
                member = guild.get_member(payload.user_id)
                if member:
                    await member.remove_roles(role)
                    channel = bot.get_channel(payload.channel_id)
                    if channel:
                        await channel.send(f"❌ {member.mention} has been removed from the {role.name} role.")

# Existing bot logic continues below...

# Bot Events
@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    scheduled_meme.start()  # Start the meme posting loop

@bot.event
async def on_member_join(member):
    guild = member.guild
    default_role = get(guild.roles, name=DEFAULT_ROLE_NAME)
    if default_role:
        await member.add_roles(default_role)

    welcome_channel = get(guild.text_channels, name=WELCOME_CHANNEL_NAME)
    if welcome_channel:
        await welcome_channel.send(f"🎉 Welcome to the server, {member.mention}!")

    log_channel = get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if log_channel:
        await log_channel.send(f"✅ {member.name} joined the server.")

@bot.event
async def on_member_remove(member):
    log_channel = get(member.guild.text_channels, name=LOG_CHANNEL_NAME)
    if log_channel:
        await log_channel.send(f"❌ {member.name} left the server.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    current_time = message.created_at.timestamp()

    # Track spam
    if user_id not in spam_tracker:
        spam_tracker[user_id] = []

    spam_tracker[user_id].append(current_time)
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if current_time - t <= SPAM_TIME_LIMIT]

    if len(spam_tracker[user_id]) > SPAM_THRESHOLD:
        mute_role = get(message.guild.roles, name="Muted")
        if not mute_role:
            mute_role = await message.guild.create_role(name="Muted")
            for channel in message.guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, speak=False)

        await message.author.add_roles(mute_role)
        log_channel = get(message.guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_channel:
            await log_channel.send(f"🚨 {message.author.name} was muted for spamming.")
        await message.channel.send(f"⚠️ {message.author.mention} has been muted for spamming.")

    await bot.process_commands(message)

# Run Bot
async def start_bot():
    async with bot:
        await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(start_bot())
