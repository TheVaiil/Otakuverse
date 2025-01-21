import discord
from discord.ext import commands, tasks
from discord.utils import get
import requests
import sqlite3
import random
import asyncio
import logging
from datetime import datetime, timezone
import aiohttp
import os
from dotenv import load_dotenv
import yt_dlp as youtube_dl

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
logging.basicConfig(level=logging.DEBUG, filename="moderation.log", format="%(asctime)s - %(message)s")

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
GITHUB_API_URL = "https://api.github.com/repos/TheVaiil/Otakuverse/commits"  # Corrected GitHub URL
CHANGELOG_CHANNEL_ID = 1330998006979498079  # Replace with your Discord changelog channel ID

# Uptime tracker
bot_start_time = datetime.now(timezone.utc)

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
                    logging.info(f"Role {role.name} assigned to {member.name} via reaction {emoji}.")

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
                    logging.info(f"Role {role.name} removed from {member.name} after reaction {emoji} was removed.")

# Bot Events
@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    print(f"Connected to {len(bot.guilds)} servers.")
    print(f"Available Commands: {list(bot.commands)}")

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

    print(f"Message Received: {message.content}")

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

# Music Commands
@bot.command()
async def play(ctx, *, query):
    """Play a song from YouTube."""
    if not ctx.author.voice:
        await ctx.send("❌ You need to be in a voice channel to play music.")
        return

    voice_channel = ctx.author.voice.channel
    if not ctx.voice_client:
        await voice_channel.connect()

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
        url = info['url']
        title = info['title']

    voice_client = ctx.voice_client
    if voice_client.is_playing():
        voice_client.stop()

    voice_client.play(discord.FFmpegPCMAudio(url))
    await ctx.send(f"🎶 Now playing: **{title}**")

@bot.command()
async def pause(ctx):
    """Pause the current song."""
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        await ctx.send("❌ No audio is currently playing.")
        return
    voice_client.pause()
    await ctx.send("⏸ Music paused.")

@bot.command()
async def resume(ctx):
    """Resume the paused song."""
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_paused():
        await ctx.send("❌ No music is paused.")
        return
    voice_client.resume()
    await ctx.send("▶️ Resumed music.")

@bot.command()
async def stop(ctx):
    """Stop the music and leave the channel."""
    voice_client = ctx.voice_client
    if not voice_client:
        await ctx.send("❌ I'm not connected to a voice channel.")
        return
    voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.send("🛑 Stopped music and left the voice channel.")

@bot.command()
async def leave(ctx):
    """Leave the voice channel."""
    voice_client = ctx.voice_client
    if not voice_client:
        await ctx.send("❌ I'm not connected to a voice channel.")
        return
    await ctx.voice_client.disconnect()
    await ctx.send("👋 Left the voice channel.")

# Commands
@bot.command()
async def ping(ctx):
    """Respond with 'Pong!' to test the bot."""
    await ctx.send("Pong!")

@bot.command()
async def bothelp(ctx):
    """
    List all available commands.
    """
    embed = discord.Embed(
        title="Available Commands",
        description="Here are the commands you can use:",
        color=discord.Color.green()
    )

    for command in bot.commands:
        embed.add_field(
            name=f"!{command.name}",
            value=command.help or "No description provided.",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command()
async def meme(ctx):
    """Get a random meme."""
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
        print(f"Error in !meme command: {e}")
        await ctx.send("❌ An error occurred while fetching memes.")

@bot.command()
async def uptime(ctx):
    """Show the bot's uptime."""
    try:
        current_time = datetime.now(timezone.utc)
        uptime_duration = current_time - bot_start_time
        days, seconds = divmod(uptime_duration.total_seconds(), 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        await ctx.send(f"🕒 Bot Uptime: {int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s")
    except Exception as e:
        logging.error(f"Error in !uptime command: {e}")
        await ctx.send("❌ An error occurred while calculating uptime.")

# Run the bot
bot.run(DISCORD_BOT_TOKEN)
