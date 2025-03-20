import discord
from discord import app_commands
from discord.ext import commands, tasks
import re
import asyncio
import openai
import logging
import nltk
from collections import deque, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from langdetect import detect
import aiofiles

# Ensure necessary NLTK data is downloaded
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('averaged_perceptron_tagger')
nltk.download('wordnet')
nltk.download('omw-1.4')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_tracker = defaultdict(lambda: deque(maxlen=5))
        self.user_warnings = defaultdict(int)
        self.blacklist = set()
        self.blacklist_pattern = None
        self.muted_users = {}
        self.load_blacklist()
        self.check_mutes.start()

    def cog_unload(self):
        """Ensure background tasks are properly stopped when the cog is unloaded."""
        self.check_mutes.cancel()

    async def load_blacklist(self):
        """Loads the blacklist words from a file asynchronously."""
        try:
            async with aiofiles.open("blacklist.txt", "r", encoding="utf-8") as f:
                self.blacklist = {line.strip().lower() for line in await f.readlines() if line.strip()}
            self.update_blacklist_pattern()
        except FileNotFoundError:
            logger.warning("Blacklist file not found. Creating an empty one.")
            async with aiofiles.open("blacklist.txt", "w", encoding="utf-8") as f:
                pass

    def update_blacklist_pattern(self):
        """Update regex pattern for blacklist words (supports Unicode characters)."""
        if self.blacklist:
            words = [re.escape(word) for word in self.blacklist]
            self.blacklist_pattern = re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE | re.UNICODE)
        else:
            self.blacklist_pattern = None

    @lru_cache(maxsize=500)
    async def check_toxicity(self, message_content: str):
        """Check message toxicity using OpenAI's Moderation API with caching."""
        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Analyze the following message and return 'toxic' or 'safe' in any language:"},
                    {"role": "user", "content": message_content}
                ],
                max_tokens=10
            )
            result = response["choices"][0]["message"]["content"].strip().lower()
            return "toxic" in result
        except Exception as e:
            logger.error(f"OpenAI API Error: {e}")
            return False

    async def ensure_muted_role(self, guild):
        """Ensures that a 'Muted' role exists in the guild."""
        mute_role = discord.utils.get(guild.roles, name="Muted")
        if not mute_role:
            try:
                mute_role = await guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False))
                for channel in guild.channels:
                    await channel.set_permissions(mute_role, send_messages=False)
            except Exception as e:
                logger.error(f"Failed to create 'Muted' role: {e}")
        return mute_role

    async def mute_user(self, message, duration=10):
        """Mutes a user and schedules an unmute."""
        mute_role = await self.ensure_muted_role(message.guild)
        await message.author.add_roles(mute_role, reason="AutoMod: Mute for violations")
        self.muted_users[message.author.id] = datetime.utcnow() + timedelta(minutes=duration)
        await message.channel.send(f"{message.author.mention} has been muted for {duration} minutes.", delete_after=10)

    @tasks.loop(minutes=1)
    async def check_mutes(self):
        """Unmutes users after their mute duration expires."""
        now = datetime.utcnow()
        to_unmute = [user_id for user_id, end_time in self.muted_users.items() if now >= end_time]

        for user_id in to_unmute:
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    mute_role = discord.utils.get(guild.roles, name="Muted")
                    if mute_role and mute_role in member.roles:
                        await member.remove_roles(mute_role, reason="AutoMod: Mute expired")
                        logger.info(f"Unmuted {member.name}")
            del self.muted_users[user_id]

    def preprocess_text(self, text):
        """Tokenizes and normalizes text (language-agnostic)."""
        try:
            language = detect(text)
        except:
            language = "unknown"

        words = nltk.word_tokenize(text, language=language if language in nltk.corpus.stopwords.fileids() else "english")
        return " ".join(words).lower()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith(self.bot.command_prefix):
            return

        now = datetime.utcnow()
        self.spam_tracker[message.author.id].append(now)
        timestamps = self.spam_tracker[message.author.id]

        # Spam detection (Decay-based)
        if len(timestamps) >= 5 and (now - timestamps[0]).total_seconds() < 10:
            await message.delete()
            self.user_warnings[message.author.id] += 1
            if self.user_warnings[message.author.id] >= 3:
                await self.mute_user(message, duration=15)
            return

        # Blacklist filtering (multilingual)
        processed_content = self.preprocess_text(message.content)
        if self.blacklist_pattern and self.blacklist_pattern.search(processed_content):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, your message contained blacklisted words.", delete_after=10)
            return

        # Toxicity detection (multilingual)
        if await self.check_toxicity(message.content):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, please avoid toxic language.", delete_after=10)
            return

async def setup(bot):
    await bot.add_cog(AutoMod(bot))
