import discord
from discord.ext import commands
import asyncio
import openai
import yaml
import re
import time
import logging
from collections import defaultdict, deque


# ============================== CONFIG UTILS ==============================
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
    This is a stand-in for what could be a more robust database solution.
    """

    def __init__(self, warning_decay_seconds=3600, warning_threshold=3, mute_duration=60):
        # For spam detection
        # user_spam_timestamps[user_id] = deque of float timestamps
        self.user_spam_timestamps = defaultdict(lambda: deque(maxlen=20))

        # For warnings & mutes
        self.user_warnings = defaultdict(int)
        self.user_mutes = defaultdict(int)

        # For time-based decay of warnings
        # user_warning_history[user_id] = [(warning_count, timestamp), ...]
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
        """
        Adds a new warning to the user and returns their new total.
        """
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
        """
        Removes warnings older than `warning_decay_seconds`.
        """
        now = time.time()
        new_list = []
        for (count, tstamp) in self.user_warning_history[user_id]:
            if (now - tstamp) < self.warning_decay_seconds:
                new_list.append((count, tstamp))
        self.user_warning_history[user_id] = new_list
        # The user's current warnings is just the length of that new list
        self.user_warnings[user_id] = len(new_list)


# ============================== SPAM CHECK ==============================
class SpamCheck:
    """
    A check that ensures a user doesn't send too many messages in a short timeframe.
    - `spam_interval` seconds
    - `spam_limit` messages within that interval
    - Optionally skip counting recognized bot commands as spam.
    """
    def __init__(self, user_data: UserDataManager, spam_interval=4, spam_limit=5, ignore_commands=True):
        self.user_data = user_data
        self.spam_interval = spam_interval
        self.spam_limit = spam_limit
        self.ignore_commands = ignore_commands
        self.logger = logging.getLogger("SpamCheck")

    async def run(self, message: discord.Message, is_command: bool):
        """
        Return True if spam is detected (the caller can handle punishment).
        """
        if self.ignore_commands and is_command:
            self.logger.debug("Skipping spam check for recognized command.")
            return False

        now = time.time()
        user_id = message.author.id
        self.user_data.add_spam_timestamp(user_id, now)

        timestamps = self.user_data.get_spam_timestamps(user_id)

        # Remove timestamps older than spam_interval
        while timestamps and (now - timestamps[0]) > self.spam_interval:
            timestamps.popleft()

        if len(timestamps) >= self.spam_limit:
            self.logger.debug(f"User {message.author} exceeded spam limit ({self.spam_limit})")
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
        # If there's nothing to compile, compile a dummy pattern
        if not pattern.strip():
            pattern = r"(?!x)x"
        self.regex = re.compile(pattern, re.IGNORECASE)
        self.logger = logging.getLogger("BlacklistCheck")

    def update_blacklist(self, words):
        pattern = "|".join(re.escape(w) for w in words)
        if not pattern.strip():
            pattern = r"(?!x)x"
        self.regex = re.compile(pattern, re.IGNORECASE)

    def run(self, content: str):
        """
        Return True if the message content contains blacklisted words.
        """
        matched = bool(self.regex.search(content))
        if matched:
            self.logger.debug("Message matched a blacklisted word.")
        return matched


# ============================== TOXICITY CHECK ==============================
class ToxicityCheck:
    """
    A check that uses OpenAI to detect whether the message is toxic.
    """
    def __init__(self, openai_api_key: str, model="gpt-3.5-turbo"):
        openai.api_key = openai_api_key
        self.model = model
        self.logger = logging.getLogger("ToxicityCheck")

    async def run(self, message: discord.Message):
        """
        Calls OpenAI to see if the text is "toxic."
        Returns True if model says "YES."
        """
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
                            "or 'NO' if the message is not toxic."
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
            if is_toxic:
                self.logger.debug(f"OpenAI classified message as toxic: {message.content!r}")
            return is_toxic
        except Exception as e:
            self.logger.error(f"Toxicity detection error: {e}")
            return False


# ============================== MESSAGE PROCESSOR ==============================
class MessageProcessor:
    """
    Encapsulates the logic for applying spam, blacklist, AI toxicity checks,
    then deciding what to do (warn, mute, delete, etc.).
    Calls process_commands once at the end of on_message.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("MessageProcessor")

        # Load config
        config = load_config()
        openai_key = config["OPENAI_API_KEY"]

        # Set up data manager
        self.user_data = UserDataManager(
            warning_decay_seconds=3600,
            warning_threshold=3,
            mute_duration=60
        )

        # Set up checks
        self.spam_check = SpamCheck(self.user_data, spam_interval=4, spam_limit=5, ignore_commands=True)
        self.blacklist_check = BlacklistCheck(words=["spamword1","spamword2","badword","anotherbadword"])
        self.toxicity_check = ToxicityCheck(openai_api_key=openai_key, model="gpt-3.5-turbo")

    async def process(self, message: discord.Message):
        """
        1) Determine if this is a recognized command.
        2) If it's not a command => run spam, blacklist, toxicity checks.
        3) If any check fails => handle punishment, skip process_commands.
        4) If it passes => call process_commands once at the end.
        5) If it's a recognized command => skip moderation checks, call process_commands once.
        """
        # We do NOT want to handle DM messages or bot messages
        if message.author.bot or not message.guild:
            return

        ctx = await self.bot.get_context(message)
        is_command = (ctx.command is not None)

        if is_command:
            # It's a recognized command => skip checks
            self.logger.debug(f"Message recognized as command: {message.content!r}")
            # Call the command processor once at the end
            await self.bot.process_commands(message)
            return
        else:
            # Not a recognized command => run checks
            # ---- 1) SPAM check
            spam_detected = await self.spam_check.run(message, is_command=False)
            if spam_detected:
                # Delete recent messages from user to contain spam
                await self.delete_recent_messages(message.channel, message.author, 10)
                await self.issue_warning(message, "Please stop spamming!")
                return  # Stop, do not call process_commands

            # ---- 2) Blacklist check
            if self.blacklist_check.run(message.content):
                await message.delete()
                await self.issue_warning(message, "Your message contained prohibited content.")
                return

            # ---- 3) Toxicity check
            if await self.toxicity_check.run(message):
                await message.delete()
                await self.issue_warning(message, "Please maintain a respectful tone.")
                return

            # If all checks pass, we do not delete or punish => we run commands
            # for unknown commands or anything else.
            self.logger.debug("No moderation flags triggered, processing commands for potential unknown commands.")
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

        # Check if we need to mute
        if current_warning_count >= self.user_data.warning_threshold:
            await self.mute_user(message)

    async def mute_user(self, message: discord.Message):
        guild = message.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")

        if not mute_role:
            mute_role = await guild.create_role(name="Muted", reason="AutoMod Mute Role")
            for channel in guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        # If user is already muted, no need
        if mute_role in message.author.roles:
            return

        await message.author.add_roles(mute_role)
        self.user_data.increment_mutes(message.author.id)

        # Announce
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
    The main Cog that sets up our MessageProcessor pipeline
    and defines optional admin commands for blacklists, warnings, etc.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("AIAutoMod")
        self.processor = MessageProcessor(bot)  # Our mega pipeline

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        All messages go through the pipeline. The pipeline decides if it's a command or needs moderation checks,
        then calls bot.process_commands exactly once if appropriate.
        """
        await self.processor.process(message)

    # ------------------ Admin Commands for Management ------------------
    @commands.command(name="add_blacklist")
    @commands.has_permissions(administrator=True)
    async def add_blacklist_command(self, ctx: commands.Context, *, word: str):
        """
        Adds a word to the blacklist and updates the regex.
        """
        # This modifies the underlying blacklisted regex
        old_pattern = self.processor.blacklist_check.regex.pattern
        words_raw = old_pattern.split("|") if "|" in old_pattern else [old_pattern]
        # Filter out dummy pattern if it exists
        words_raw = [w for w in words_raw if "(?!x)x" not in w and w.strip()]
        # Convert backslash escapes to actual words
        words_list = [re.sub(r"\\", "", w) for w in words_raw]

        # Add the new word
        words_list.append(word.lower())
        # Rebuild the pattern
        combined = "|".join(re.escape(w) for w in words_list if w.strip())
        if not combined:
            combined = r"(?!x)x"
        self.processor.blacklist_check.regex = re.compile(combined, re.IGNORECASE)

        await ctx.send(f"Added `{word}` to the blacklist.")

    @commands.command(name="remove_blacklist")
    @commands.has_permissions(administrator=True)
    async def remove_blacklist_command(self, ctx: commands.Context, *, word: str):
        """
        Removes a word from the blacklist regex.
        """
        old_pattern = self.processor.blacklist_check.regex.pattern
        words_raw = old_pattern.split("|") if "|" in old_pattern else [old_pattern]
        words_raw = [re.sub(r"\\", "", w) for w in words_raw]  # unescape
        # Filter out the removed word
        new_list = [w for w in words_raw if w.lower() != word.lower() and "(?!x)x" not in w and w.strip()]

        if not new_list:
            # If no words left, use dummy pattern
            combined = r"(?!x)x"
        else:
            combined = "|".join(re.escape(w) for w in new_list)

        self.processor.blacklist_check.regex = re.compile(combined, re.IGNORECASE)

        await ctx.send(f"Removed `{word}` from the blacklist.")

    @commands.command(name="show_blacklist")
    @commands.has_permissions(administrator=True)
    async def show_blacklist_command(self, ctx: commands.Context):
        """
        Shows the current blacklisted words.
        """
        pattern = self.processor.blacklist_check.regex.pattern
        if "(?!x)x" in pattern or not pattern.strip():
            # No real words
            desc = "No blacklisted words."
        else:
            raw_list = pattern.split("|")
            # unescape
            words_list = [re.sub(r"\\", "", w) for w in raw_list]
            desc = "\n".join(f"- {word}" for word in words_list)

        embed = discord.Embed(title="Blacklisted Words", description=desc, color=discord.Color.red())
        await ctx.send(embed=embed)

    @commands.command(name="user_status")
    @commands.has_permissions(administrator=True)
    async def user_status_command(self, ctx: commands.Context, member: discord.Member):
        """
        Check the number of warnings and mutes for a specific user.
        """
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
        """
        Clears all warnings for a user.
        """
        self.processor.user_data.clear_warnings(member.id)
        await ctx.send(f"Cleared all warnings for {member.mention}.")


async def setup(bot: commands.Bot):
    """
    The standard setup function. 
    This code is loaded once by your dynamic loader or manually. 
    """
    await bot.add_cog(AIAutoMod(bot))
