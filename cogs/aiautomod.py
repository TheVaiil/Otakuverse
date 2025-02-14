import discord
from discord import app_commands
from discord.ext import commands, tasks
import re
import asyncio
import openai
import logging
from collections import deque, defaultdict
from datetime import datetime, timedelta

# Configure logging
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
        
    def load_blacklist(self):
        try:
            with open("blacklist.txt", "r") as f:
                self.blacklist = set(line.strip().lower() for line in f)
            self.update_blacklist_pattern()
        except FileNotFoundError:
            logger.warning("Blacklist file not found. Creating an empty one.")
            with open("blacklist.txt", "w"):
                pass
    
    def update_blacklist_pattern(self):
        if self.blacklist:
            self.blacklist_pattern = re.compile(
                r"\b(" + "|".join(re.escape(word) for word in self.blacklist) + r")\b",
                re.IGNORECASE
            )
        else:
            self.blacklist_pattern = None
    
    async def check_toxicity(self, message):
        """Check message toxicity using OpenAI GPT with caching."""
        if not hasattr(self.bot, "toxicity_cache"):
            self.bot.toxicity_cache = {}
        
        if message.content in self.bot.toxicity_cache:
            return self.bot.toxicity_cache[message.content]
        
        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[{"role": "system", "content": "Classify the following message as 'toxic' or 'safe':"},
                          {"role": "user", "content": message.content}],
                max_tokens=10
            )
            result = response["choices"][0]["message"]["content"].strip().lower()
            toxicity = "toxic" in result
            self.bot.toxicity_cache[message.content] = toxicity
            return toxicity
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            return False

    async def mute_user(self, message, duration=10):
        """Mutes a user and schedules unmute."""
        mute_role = discord.utils.get(message.guild.roles, name="Muted")
        if not mute_role:
            mute_role = await message.guild.create_role(  # Fixed line
                name="Muted",
                permissions=discord.Permissions(send_messages=False)
            )  # Added closing parenthesis here
        
        await message.author.add_roles(mute_role)
        self.muted_users[message.author.id] = datetime.utcnow() + timedelta(minutes=duration)
        await message.channel.send(f"{message.author.mention} has been muted for {duration} minutes.")
        
    @tasks.loop(minutes=1)
    async def check_mutes(self):
        """Unmutes users after their mute duration expires."""
        now = datetime.utcnow()
        to_unmute = [user_id for user_id, end_time in self.muted_users.items() if now >= end_time]
        
        for user_id in to_unmute:
            for guild in self.bot.guilds:
                if member := guild.get_member(user_id):
                    mute_role = discord.utils.get(guild.roles, name="Muted")
                    if mute_role:
                        await member.remove_roles(mute_role)
                        logger.info(f"Unmuted {member.name}")
            del self.muted_users[user_id]
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith(self.bot.command_prefix):
            return
        
        # Spam detection
        now = datetime.utcnow()
        self.spam_tracker[message.author.id].append(now)
        timestamps = self.spam_tracker[message.author.id]
        
        if len(timestamps) >= 5 and (now - timestamps[0]).total_seconds() < 10:
            await message.delete()
            self.user_warnings[message.author.id] += 1
            if self.user_warnings[message.author.id] >= 3:
                await self.mute_user(message)
            return
        
        # Blacklist filtering
        if self.blacklist_pattern and self.blacklist_pattern.search(message.content):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, your message contained blacklisted words.")
            return
        
        # Toxicity detection
        if await self.check_toxicity(message):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, please avoid toxic language.")
            return
    
    @app_commands.command(name="add_blacklist", description="Add a word to the blacklist")
    @app_commands.default_permissions(manage_messages=True)
    async def add_blacklist(self, interaction: discord.Interaction, word: str):
        """Adds a word to the blacklist (Mod only)"""
        word = word.lower()
        self.blacklist.add(word)
        with open("blacklist.txt", "a") as f:
            f.write(word + "\n")
        self.update_blacklist_pattern()
        await interaction.response.send_message(f"Added `{word}` to the blacklist.", ephemeral=True)
    
    @app_commands.command(name="remove_blacklist", description="Remove a word from the blacklist")
    @app_commands.default_permissions(manage_messages=True)
    async def remove_blacklist(self, interaction: discord.Interaction, word: str):
        """Removes a word from the blacklist (Mod only)"""
        word = word.lower()
        if word in self.blacklist:
            self.blacklist.remove(word)
            with open("blacklist.txt", "w") as f:
                f.write("\n".join(self.blacklist))
            self.update_blacklist_pattern()
            await interaction.response.send_message(f"Removed `{word}` from the blacklist.", ephemeral=True)
        else:
            await interaction.response.send_message(f"`{word}` is not in the blacklist.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AutoMod(bot))