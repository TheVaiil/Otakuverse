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
    This approach is faster for large sets of blacklisted words than checking each word with 'in'.
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
        self.warning_threshold = 3       # Warnings before mute
        self.spam_interval = 4          # Check messages within last N seconds
        self.spam_message_limit = 5     # How many messages in spam_interval triggers spam
        self.mute_duration = 60         # Mute duration in seconds
        self.warning_decay_seconds = 3600  # 1-hour decay for warnings (optional)

        # For storing time-based data about warnings to allow decay
        # user_warning_timestamps[user_id] = [ (warning_count, timestamp), ... ]
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

        # === Spam Detection ===
        if await self.detect_spam(message):
            # Delete the most recent messages from user to contain spam
            await self.delete_recent_messages(message.channel, message.author, 10)
            await self.issue_warning(message, "Please stop spamming!")
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


    async def detect_spam(self, message: discord.Message) -> bool:
        """
        Detect if a user is spamming based on how many messages they've sent
        within a recent time interval (self.spam_interval).
        """
        user_id = message.author.id
        now = time.time()
        
        # Add current timestamp to user's message history
        self.user_message_count[user_id].append(now)
        
        # Remove timestamps older than spam_interval from the left of the deque
        while self.user_message_count[user_id]:
            if now - self.user_message_count[user_id][0] > self.spam_interval:
                self.user_message_count[user_id].popleft()
            else:
                break
        
        # Check if number of messages in the last spam_interval seconds exceeds spam_message_limit
        if len(self.user_message_count[user_id]) >= self.spam_message_limit:
            return True
        return False


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
                max_tokens=5,  # We only need a short reply
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

        # Decay old warnings
        self.decay_warnings(user_id)

        # Increment warnings
        self.user_warnings[user_id] += 1
        current_warning_count = self.user_warnings[user_id]

        # Record the timestamp of this warning (for future decay)
        self.user_warning_timestamps[user_id].append((current_warning_count, time.time()))

        # Send a warning message
        warning_msg = await message.channel.send(
            f"{message.author.mention}, {reason} "
            f"This is warning #{current_warning_count}."
        )
        await asyncio.sleep(3)  # Show warning briefly
        await warning_msg.delete()

        # Mute if over threshold
        if current_warning_count >= self.warning_threshold:
            await self.mute_user(message)


    def decay_warnings(self, user_id: int):
        """
        Reduce (or reset) the user's warnings if they've gone a long time without infractions.
        This runs each time a user receives a new warning, ensuring older warnings don't accumulate forever.
        """
        if not self.user_warning_timestamps[user_id]:
            return

        now = time.time()
        # Filter out old warnings
        self.user_warning_timestamps[user_id] = [
            (warn_count, tstamp) for (warn_count, tstamp) in self.user_warning_timestamps[user_id]
            if (now - tstamp) < self.warning_decay_seconds
        ]

        # The latest warning count is the length of the filtered list
        # Or you can sum up all or track the highest. For simplicity, let's keep it simple:
        self.user_warnings[user_id] = len(self.user_warning_timestamps[user_id])


    async def mute_user(self, message: discord.Message):
        """
        Mute the user by assigning the 'Muted' role. Unmute after self.mute_duration.
        """
        guild = message.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")
        
        if not mute_role:
            # Create a Muted role if it doesn't exist
            mute_role = await guild.create_role(name="Muted", reason="AutoMod Mute Role")
            for channel in guild.channels:
                # Deny send_messages and reactions
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        if mute_role in message.author.roles:
            # Already muted; no need to reassign
            return

        await message.author.add_roles(mute_role)
        self.user_mutes[message.author.id] += 1
        
        mute_msg = await message.channel.send(
            f"{message.author.mention} has been muted due to repeated violations."
        )

        # Wait for the mute duration, then unmute
        await asyncio.sleep(self.mute_duration)
        await message.author.remove_roles(mute_role)
        await mute_msg.delete()

        unmute_msg = await message.channel.send(f"{message.author.mention} has been unmuted.")
        await asyncio.sleep(2)
        await unmute_msg.delete()


    async def delete_recent_messages(self, channel: discord.TextChannel, author: discord.Member, limit: int):
        """
        Delete the recent `limit` messages from a specific user, including the triggering message.
        """
        async for msg in channel.history(limit=limit):
            if msg.author == author:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass  # message already deleted


    @commands.command()
    @commands.has_permissions(administrator=True)
    async def add_blacklist(self, ctx, *, word):
        """Add a word to the blacklist and recompile the regex."""
        self.blacklisted_words.append(word.lower())
        self.blacklist_pattern = compile_blacklisted_regex(self.blacklisted_words)
        await ctx.send(f"Added `{word}` to the blacklist.")


    @commands.command()
    @commands.has_permissions(administrator=True)
    async def remove_blacklist(self, ctx, *, word):
        """Remove a word from the blacklist and recompile the regex."""
        self.blacklisted_words = [w for w in self.blacklisted_words if w != word.lower()]
        self.blacklist_pattern = compile_blacklisted_regex(self.blacklisted_words)
        await ctx.send(f"Removed `{word}` from the blacklist.")


    @commands.command()
    @commands.has_permissions(administrator=True)
    async def show_blacklist(self, ctx):
        """Show the current blacklist."""
        embed = discord.Embed(title="Blacklisted Words", color=discord.Color.red())
        if self.blacklisted_words:
            embed.description = "\n".join([f"- {word}" for word in self.blacklisted_words])
        else:
            embed.description = "No blacklisted words."
        await ctx.send(embed=embed)


    @commands.command()
    @commands.has_permissions(administrator=True)
    async def user_status(self, ctx, member: discord.Member):
        """
        Check the number of warnings and mutes for a specific user.
        Also shows how many warnings have been decayed if that feature is used often.
        """
        warnings = self.user_warnings.get(member.id, 0)
        mutes = self.user_mutes.get(member.id, 0)

        embed = discord.Embed(
            title=f"User Status: {member.display_name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Warnings", value=warnings, inline=False)
        embed.add_field(name="Mutes", value=mutes, inline=False)
        await ctx.send(embed=embed)


    @commands.command()
    @commands.has_permissions(administrator=True)
    async def clear_warnings(self, ctx, member: discord.Member):
        """
        Manually clear all warnings for a user (resets them to 0).
        Useful if you want to pardon a user or reset after a certain time.
        """
        self.user_warnings[member.id] = 0
        self.user_warning_timestamps[member.id].clear()
        await ctx.send(f"Cleared all warnings for {member.mention}.")


async def setup(bot: commands.Bot):
    """Properly load the AIAutoMod cog."""
    await bot.add_cog(AIAutoMod(bot))
