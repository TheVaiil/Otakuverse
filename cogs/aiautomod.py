import discord
from discord.ext import commands
import asyncio
from collections import defaultdict, deque
import openai
import yaml
import re
import time


def compile_blacklisted_regex(words):
    """
    Compiles a single regex pattern that matches any of the words in the list.
    This approach is faster for large sets of blacklisted words than checking each word individually.
    """
    if not words:
        # If no blacklisted words, compile an always-false regex
        return re.compile(r'(?!x)x')
    pattern = r"|".join(re.escape(w) for w in words)
    return re.compile(pattern, re.IGNORECASE)


class AIAutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Tracking user messages for spam detection
        # user_message_count[user_id] = deque of timestamps (floats)
        self.user_message_count = defaultdict(lambda: deque(maxlen=10))
        
        # Tracks warnings and mutes
        self.user_warnings = defaultdict(int)
        self.user_mutes = defaultdict(int)
        
        # Configuration for threshold and intervals
        self.warning_threshold = 3         # Warnings before mute
        self.spam_interval = 4            # Check messages within last N seconds
        self.spam_message_limit = 5       # N messages within spam_interval => spam
        self.mute_duration = 60           # Mute duration in seconds
        self.warning_decay_seconds = 3600 # 1-hour decay for old warnings (optional)

        # For storing time-based data about warnings to allow decay
        # user_warning_timestamps[user_id] = [(warning_count, timestamp), ...]
        self.user_warning_timestamps = defaultdict(list)

        # Load config and set up OpenAI
        with open("config/config.yaml", "r") as config_file:
            config = yaml.safe_load(config_file)

        openai.api_key = config["OPENAI_API_KEY"]

        # Basic blacklisted words
        self.blacklisted_words = ["spamword1", "spamword2", "badword", "anotherbadword"]
        self.blacklist_pattern = compile_blacklisted_regex(self.blacklisted_words)


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot or system messages
        if message.author.bot or not message.guild:
            return

        # 1. Check if this is a valid command. If so, skip moderation checks.
        ctx = await self.bot.get_context(message)
        if ctx.command is not None:
            # It's a recognized command (e.g., !helpme), so let's process it and skip spam checks.
            await self.bot.process_commands(message)
            return

        # 2. Not a valid command => run moderation checks (spam, blacklist, AI toxicity).

        # === Spam Detection ===
        if await self.detect_spam(message):
            # Delete the most recent messages from this user to contain spam
            await self.delete_recent_messages(message.channel, message.author, 10)
            await self.issue_warning(message, "Please stop spamming!")
            # No need to process further commands in this case
            return

        # === Blacklisted Words Detection ===
        if self.blacklist_pattern.search(message.content):
            await message.delete()
            await self.issue_warning(message, "Your message contained prohibited content.")
            return

        # === AI Toxicity Check ===
        if await self.detect_toxicity(message):
            await message.delete()
            await self.issue_warning(message, "Please maintain a respectful tone.")
            return

        # 3. Finally, if it’s not recognized as a command but passes moderation, we still
        #    call process_commands here to handle unknown commands or other potential processing.
        await self.bot.process_commands(message)


    async def detect_spam(self, message: discord.Message) -> bool:
        """
        Detect if a user is spamming by checking how many messages they've sent
        within the last 'spam_interval' seconds.
        """
        user_id = message.author.id
        now = time.time()
        
        # Add current timestamp to user's message history
        self.user_message_count[user_id].append(now)
        
        # Remove timestamps older than spam_interval from the left side of the deque
        while self.user_message_count[user_id] and now - self.user_message_count[user_id][0] > self.spam_interval:
            self.user_message_count[user_id].popleft()
        
        # If user sends 'spam_message_limit' or more messages in 'spam_interval' seconds => spam
        return len(self.user_message_count[user_id]) >= self.spam_message_limit


    async def detect_toxicity(self, message: discord.Message) -> bool:
        """
        Use OpenAI's ChatCompletion to detect toxicity. 
        Expect the AI to respond with "YES" or "NO" only.
        """
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",  # or "gpt-4" if you have access
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a toxicity detection system. "
                            "Respond ONLY with 'YES' if the message is toxic, or 'NO' if it is not toxic."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Is the following message toxic? '{message.content}'"
                    }
                ],
                max_tokens=5,
                temperature=0.0
            )
            reply = response['choices'][0]['message']['content'].strip().lower()
            # If AI detects toxicity, it replies "YES"
            return reply.startswith("yes")
        except Exception as e:
            print(f"Toxicity detection error: {e}")
            return False


    async def issue_warning(self, message: discord.Message, reason: str):
        """
        Issue a warning to the user, then handle escalation (muting) if needed.
        Also handle warning decay if it's been a while since the last warning.
        """
        user_id = message.author.id

        # Decay old warnings first
        self.decay_warnings(user_id)

        # Increment warnings
        self.user_warnings[user_id] += 1
        current_warning_count = self.user_warnings[user_id]

        # Record timestamp of this warning (for future decay)
        self.user_warning_timestamps[user_id].append((current_warning_count, time.time()))

        # Send a warning message
        warning_msg = await message.channel.send(
            f"{message.author.mention}, {reason} "
            f"This is warning #{current_warning_count}."
        )
        await asyncio.sleep(3)
        await warning_msg.delete()

        # Mute if over threshold
        if current_warning_count >= self.warning_threshold:
            await self.mute_user(message)


    def decay_warnings(self, user_id: int):
        """
        Reduce or remove older warnings if they've exceeded 'warning_decay_seconds'.
        This prevents infinite accumulation of warnings.
        """
        if not self.user_warning_timestamps[user_id]:
            return

        now = time.time()
        # Keep only warnings that occurred within the decay window
        self.user_warning_timestamps[user_id] = [
            (count, tstamp)
            for (count, tstamp) in self.user_warning_timestamps[user_id]
            if (now - tstamp) < self.warning_decay_seconds
        ]

        # The user's current warning count is then the number of valid (non-expired) warnings
        self.user_warnings[user_id] = len(self.user_warning_timestamps[user_id])


    async def mute_user(self, message: discord.Message):
        """
        Mute the user by assigning a 'Muted' role. Unmute after 'mute_duration' seconds.
        """
        guild = message.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")
        
        # Create a Muted role if it doesn't exist
        if not mute_role:
            mute_role = await guild.create_role(name="Muted", reason="AutoMod Mute Role")
            for channel in guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        # Check if user is already muted
        if mute_role in message.author.roles:
            return

        await message.author.add_roles(mute_role)
        self.user_mutes[message.author.id] += 1
        
        mute_msg = await message.channel.send(
            f"{message.author.mention} has been muted due to repeated violations."
        )

        # Mute duration
        await asyncio.sleep(self.mute_duration)
        await message.author.remove_roles(mute_role)
        await mute_msg.delete()

        unmute_msg = await message.channel.send(f"{message.author.mention} has been unmuted.")
        await asyncio.sleep(2)
        await unmute_msg.delete()


    async def delete_recent_messages(self, channel: discord.TextChannel, author: discord.Member, limit: int):
        """
        Delete the recent `limit` messages from a specific user, including the triggering message.