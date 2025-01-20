"""
====================================================
Otakuverse Discord Bot
Copyright © 2025 Otakuverse Community
Developed for the Otakuverse Discord server by [Your Discord Username]
====================================================

Description:
This bot is designed for the Otakuverse Discord server. It includes features such as:
1. Moderation tools (warnings, mutes, bans, etc.).
2. Random meme posting (Imgflip integration).
3. Scheduled meme posting.
4. Spam detection and management.

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

# Logging setup
logging.basicConfig(filename="moderation.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Intents and bot setup
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Variables
WELCOME_CHANNEL_NAME = "welcome"
LOG_CHANNEL_NAME = "moderation-log"
DEFAULT_ROLE_NAME = "Member"
WARNING_LIMIT = 3
SPAM_THRESHOLD = 5
SPAM_TIME_LIMIT = 10

# Temporary spam tracker
spam_tracker = {}

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

    welcome_channel = get(guild.text_channels, name=welcome)
    if welcome_channel:
        await welcome_channel.send(f"🎉 Welcome to the server, {member.mention}!")

    log_channel = get(guild.text_channels, name=logs)
    if log_channel:
        await log_channel.send(f"✅ {member.name} joined the server.")

@bot.event
async def on_member_remove(member):
    log_channel = get(member.guild.text_channels, name=logs)
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

# Moderation Commands
@bot.command()
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, reason=None):
    with sqlite3.connect('warnings.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT warning_count FROM warnings WHERE user_id = ? AND guild_id = ?', (member.id, ctx.guild.id))
        result = cursor.fetchone()

        warning_count = result[0] + 1 if result else 1
        if result:
            cursor.execute('UPDATE warnings SET warning_count = ? WHERE user_id = ? AND guild_id = ?', (warning_count, member.id, ctx.guild.id))
        else:
            cursor.execute('INSERT INTO warnings (user_id, guild_id, warning_count) VALUES (?, ?, ?)', (member.id, ctx.guild.id, 1))

    await ctx.send(f"⚠️ {member.mention} has been warned. Reason: {reason}")
    if warning_count >= WARNING_LIMIT:
        await mute(ctx, member, duration=10, reason="Exceeded warning limit.")

@bot.command()
async def warnings(ctx, member: discord.Member):
    with sqlite3.connect('warnings.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT warning_count FROM warnings WHERE user_id = ? AND guild_id = ?', (member.id, ctx.guild.id))
        result = cursor.fetchone()

    if result:
        await ctx.send(f"⚠️ {member.mention} has {result[0]} warning(s).")
    else:
        await ctx.send(f"✅ {member.mention} has no warnings.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, duration: int = 0, *, reason=None):
    guild = ctx.guild
    mute_role = get(guild.roles, name="Muted")
    if not mute_role:
        mute_role = await guild.create_role(name="Muted")
        for channel in guild.channels:
            await channel.set_permissions(mute_role, send_messages=False, speak=False)

    await member.add_roles(mute_role)
    await ctx.send(f"🤐 {member.mention} has been muted. Reason: {reason}")
    if duration > 0:
        await asyncio.sleep(duration * 60)
        await member.remove_roles(mute_role)

# Meme Commands
@bot.command()
async def meme(ctx):
    try:
        url = "https://api.imgflip.com/get_memes"
        response = requests.get(url)
        data = response.json()
        if data["success"]:
            memes = data["data"]["memes"]
            random_meme = random.choice(memes)

            embed = discord.Embed(
                title=random_meme['name'],
                description="Here's a random meme for you!",
                color=discord.Color.blue()
            )
            embed.set_image(url=random_meme['url'])

            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to fetch memes. Please try again later.")
    except Exception as e:
        print(f"Error in meme command: {e}")
        await ctx.send("❌ An error occurred while fetching memes.")

# Scheduled Meme Posting
@tasks.loop(hours=1)
async def scheduled_meme():
    channel = bot.get_channel(1330998006979498079)
    if channel:
        url = "https://api.imgflip.com/get_memes"
        response = requests.get(url)
        data = response.json()
        if data["success"]:
            memes = data["data"]["memes"]
            random_meme = random.choice(memes)

            embed = discord.Embed(
                title=random_meme['name'],
                description="Scheduled random meme!",
                color=discord.Color.purple()
            )
            embed.set_image(url=random_meme['url'])

            await channel.send(embed=embed)
    else:
        print("Error: Channel not found. Check YOUR_CHANNEL_ID.")

# Run Bot
async def start_bot():
    async with bot:
        await bot.start("MTMzMDY2MjI2Mzk2NjkyNDg3Mw.GvtS5K.HdRujHFVjCdNXMJx5GhvK0PJwyGh2rzl7jm9ks")

if __name__ == "__main__":
    asyncio.run(start_bot())
