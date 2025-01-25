import discord
from discord.ext import commands
import asyncio
import openai
import yaml
import re
import time
import logging
from collections import defaultdict, deque

def load_config():
    """
    Loads your config for the OpenAI API key and any other settings.
    """
    with open("config/config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# ============================== DATA MANAGER ==============================
class UserDataManager:
    """
    Manages warnings, mutes, spam timestamps, etc.
    """

    def __init__(self, warning_decay_seconds=3600, warning_threshold=3, mute_duration=60):
        # For spam detection
        self.user_spam_timestamps = defaultdict(lambda: deque(maxlen=20))

        # For warnings & mutes
        self.user_warnings = defaultdict(int)
        self.user_mutes = defaultdict(int)

        # For time-based decay of warnings
        self.user_warning_history = defaultdict(list)

        # Config
        self.warning_decay_seconds = warning_decay_seconds
        self.warning_threshold = warning_threshold
        self.mute_duration = mute_duration

    def add_spam_timestamp(self, user_id: int, timestamp: float):
        self.user_spam_timestamps[user_id].append(timestamp)

    def get_spam_timestamps(self, user_id: int):
        return self.user_spam_timestamps[user_id]

    def clear_spam_timestamps(self, user_id: int):
        self.user_spam_timestamps[user_id].clear()

    def increment_warning(self, user_id: int):
        self.decay_old_warnings(user_id)

        self.user_warnings[user_id] += 1
        current = self.user_warnings[user_id]
        self.user_warning_history[user_id].append((current, time.time()))
        return current

    def get_warning_count(self, user_id: int):
        self.decay_old_warnings(user_id)
        return self.user_warnings[user_id]

    def clear_warnings(self, user_id: int):
        self.user_warnings[user_id] = 0
        self.user_warning_history[user_id].clear()

    def increment_mutes(self, user_id: int):
        self.user_mutes[user_id] += 1

    def get_mute_count(self, user_id: int):
        return self.user_mutes[user_id]

    def decay_old_warnings(self, user_id: int):
        now = time.time()
        new_list = []
        for (count, tstamp) in self.user_warning_history[user_id]:
            if (now - tstamp) < self.warning_decay_seconds:
                new_list.append((count, tstamp))
        self.user_warning_history[user_id] = new_list
        self.user_warnings[user_id] = len(new_list)

# ============================== SPAM CHECK ==============================
class SpamCheck:
    """
    A check that ensures a user doesn't send too many messages in a short timeframe.
    - spam_interval seconds
    - spam_limit messages within that interval
    - ignore_commands => if True, recognized commands won't count as spam
    """
    def __init__(self, user_data: UserDataManager, spam_interval=4, spam_limit=5, ignore_commands=True):
        self.user_data = user_data
        self.spam_interval = spam_interval
        self.spam_limit = spam_limit
        self.ignore_commands = ignore_commands
        self.logger = logging.getLogger("SpamCheck")

    async def run(self, message: discord.Message, is_command: bool):
        if self.ignore_commands and is_command:
            return False  # skip counting recognized commands

        now = time.time()
        user_id = message.author.id
        self.user_data.add_spam_timestamp(user_id, now)

        timestamps = self.user_data.get_spam_timestamps(user_id)

        # Remove old timestamps outside spam_interval
        while timestamps and (now - timestamps[0]) > self.spam_interval:
            timestamps.popleft()

        # If user hit spam_limit within spam_interval, flagged as spam
        if len(timestamps) >= self.spam_limit:
            self.logger.debug(f"Spam detected for user {message.author}")
            return True
        return False

# ============================== BLACKLIST CHECK ==============================
class BlacklistCheck:
    """
    A check that detects blacklisted words using a compiled regex.
    """
    def __init__(self, words=None):
        if words is None:
            words = ["spamword1", "spamword2", "badword", "anotherbadword"]
        pattern = "|".join(re.escape(w) for w in words)
        if not pattern.strip():
            pattern = r"(?!x)x"
        self.regex = re.compile(pattern, re.IGNORECASE)
        self.logger = logging.getLogger("BlacklistCheck")

    def run(self, content: str):
        """
        Return True if the message contains blacklisted words.
        """
        matched = bool(self.regex.search(content))
        if matched:
            self.logger.debug("Blacklisted word detected.")
        return matched

    def update_blacklist(self, words):
        pattern = "|".join(re.escape(w) for w in words) or r"(?!x)x"
        self.regex = re.compile(pattern, re.IGNORECASE)

# ============================== TOXICITY CHECK ==============================
class ToxicityCheck:
    def __init__(self, openai_api_key: str, model="gpt-3.5-turbo"):
        import openai
        openai.api_key = openai_api_key
        self.model = model
        self.logger = logging.getLogger("ToxicityCheck")

    async def run(self, message: discord.Message):
        try:
            import openai
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a toxicity detection system. "
                            "Respond ONLY with 'YES' if the message is toxic, "
                            "or 'NO' if it is not toxic."
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
            is_toxic = reply.startswith("yes")
            return is_toxic
        except Exception as e:
            self.logger.error(f"Toxicity detection error: {e}")
            return False

# ============================== MESSAGE PROCESSOR ==============================
class MessageProcessor:
    """
    One pipeline: We run checks only if it's NOT a recognized command. 
    Then at the very end, we call bot.process_commands exactly once for all messages.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        config = load_config()
        self.logger = logging.getLogger("MessageProcessor")

        # Our user data manager
        self.user_data = UserDataManager(
            warning_decay_seconds=3600,
            warning_threshold=3,
            mute_duration=60
        )

        # Checks
        self.spam_check = SpamCheck(self.user_data, spam_interval=4, spam_limit=5, ignore_commands=True)
        self.blacklist_check = BlacklistCheck()
        self.toxicity_check = ToxicityCheck(config["OPENAI_API_KEY"], model="gpt-3.5-turbo")

    async def process_message(self, message: discord.Message):
        """
        If it's a recognized command -> skip checks. 
        If not a command -> do spam, blacklist, toxicity checks. 
        Then call process_commands exactly once at the end.
        """

        # 1) If it's a bot or non-guild message, do nothing
        if message.author.bot or not message.guild:
            return

        # 2) Check if it's a recognized command
        ctx = await self.bot.get_context(message)
        is_command = (ctx.command is not None)

        if not is_command:
            # =========== Run moderation checks ============
            if await self.spam_check.run(message, is_command=False):
                await self.delete_recent_messages(message.channel, message.author, 10)
                await self.issue_warning(message, "Please stop spamming!")
                return  # Do NOT process_commands -> we already moderated

            if self.blacklist_check.run(message.content):
                await message.delete()
                await self.issue_warning(message, "Your message contained prohibited content.")
                return

            if await self.toxicity_check.run(message):
                await message.delete()
                await self.issue_warning(message, "Please maintain a respectful tone.")
                return

        # 3) Finally, call process_commands once for everything (commands or not).
        await self.bot.process_commands(message)

    async def delete_recent_messages(self, channel: discord.TextChannel, author: discord.Member, limit: int):
        async for msg in channel.history(limit=limit):
            if msg.author == author:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass

    async def issue_warning(self, message: discord.Message, reason: str):
        current_warning_count = self.user_data.increment_warning(message.author.id)
        warn_text = (f"{message.author.mention}, {reason} "
                     f"(Warning #{current_warning_count})")
        warning_msg = await message.channel.send(warn_text)
        await asyncio.sleep(3)
        await warning_msg.delete()

        if current_warning_count >= self.user_data.warning_threshold:
            await self.mute_user(message)

    async def mute_user(self, message: discord.Message):
        guild = message.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")

        if not mute_role:
            mute_role = await guild.create_role(name="Muted", reason="AutoMod Mute Role")
            for channel in guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        if mute_role in message.author.roles:
            return

        await message.author.add_roles(mute_role)
        self.user_data.increment_mutes(message.author.id)

        mute_msg = await message.channel.send(
            f"{message.author.mention} has been muted due to repeated violations."
        )
        await asyncio.sleep(self.user_data.mute_duration)
        await message.author.remove_roles(mute_role)
        await mute_msg.delete()

        unmute_msg = await message.channel.send(f"{message.author.mention} has been unmuted.")
        await asyncio.sleep(2)
        await unmute_msg.delete()

# ============================== THE ACTUAL COG ==============================
class AIAutoMod(commands.Cog):
    """
    Main Cog that wires up the single on_message event.
    Also includes admin commands for blacklists, warnings, etc.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("AIAutoMod")
        self.processor = MessageProcessor(bot)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Handles incoming messages for moderation.
        Ensures commands are processed only once.
        """
        if message.author.bot:  # Ignore bot messages
            return

        # Check if the message is a recognized command
        ctx = await self.bot.get_context(message)
        if ctx.command:  # Skip moderation checks if it's a command
            return

        # Process moderation logic for non-commands
        await self.processor.process_message(message)

    # ------------------ Admin Commands for Management ------------------
    @commands.command(name="add_blacklist")
    @commands.has_permissions(administrator=True)
    async def add_blacklist_command(self, ctx: commands.Context, *, word: str):
        """Adds a word to the blacklist."""
        # Extract the current pattern into a list
        pattern = self.processor.blacklist_check.regex.pattern
        raw_list = pattern.split("|") if "|" in pattern else [pattern]
        # unescape
        raw_list = [re.sub(r"\\", "", w) for w in raw_list]
        # filter out dummy pattern if present
        raw_list = [w for w in raw_list if "(?!x)x" not in w and w.strip()]

        raw_list.append(word.lower())
        new_pattern = "|".join(re.escape(w) for w in raw_list) or r"(?!x)x"
        self.processor.blacklist_check.regex = re.compile(new_pattern, re.IGNORECASE)
        await ctx.send(f"Added `{word}` to the blacklist.")

    @commands.command(name="remove_blacklist")
    @commands.has_permissions(administrator=True)
    async def remove_blacklist_command(self, ctx: commands.Context, *, word: str):
        """Removes a word from the blacklist."""
        pattern = self.processor.blacklist_check.regex.pattern
        raw_list = pattern.split("|") if "|" in pattern else [pattern]
        raw_list = [re.sub(r"\\", "", w) for w in raw_list]
        new_list = [w for w in raw_list if w.lower() != word.lower() and "(?!x)x" not in w and w.strip()]

        if not new_list:
            new_pattern = r"(?!x)x"
        else:
            new_pattern = "|".join(re.escape(w) for w in new_list)
        self.processor.blacklist_check.regex = re.compile(new_pattern, re.IGNORECASE)

        await ctx.send(f"Removed `{word}` from the blacklist.")

    @commands.command(name="show_blacklist")
    @commands.has_permissions(administrator=True)
    async def show_blacklist_command(self, ctx: commands.Context):
        """Shows the current blacklist."""
        pattern = self.processor.blacklist_check.regex.pattern
        if "(?!x)x" in pattern or not pattern.strip():
            desc = "No blacklisted words."
        else:
            raw_list = pattern.split("|")
            words_list = [re.sub(r"\\", "", w) for w in raw_list]
            desc = "\n".join(f"- {word}" for word in words_list)

        embed = discord.Embed(title="Blacklisted Words", description=desc, color=discord.Color.red())
        await ctx.send(embed=embed)

    @commands.command(name="user_status")
    @commands.has_permissions(administrator=True)
    async def user_status_command(self, ctx: commands.Context, member: discord.Member):
        """Check the number of warnings and mutes for a user."""
        ud = self.processor.user_data
        warnings = ud.get_warning_count(member.id)
        mutes = ud.get_mute_count(member.id)

        embed = discord.Embed(title=f"User Status: {member.display_name}", color=discord.Color.blue())
        embed.add_field(name="Warnings", value=str(warnings), inline=False)
        embed.add_field(name="Mutes", value=str(mutes), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="clear_warnings")
    @commands.has_permissions(administrator=True)
    async def clear_warnings_command(self, ctx: commands.Context, member: discord.Member):
        """Clears all warnings for a user."""
        self.processor.user_data.clear_warnings(member.id)
        await ctx.send(f"Cleared all warnings for {member.mention}.")

async def setup(bot: commands.Bot):
    """Standard setup for dynamic loading."""
    await bot.add_cog(AIAutoMod(bot))
