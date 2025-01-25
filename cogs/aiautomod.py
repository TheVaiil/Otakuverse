import discord
from discord.ext import commands
import asyncio
from collections import defaultdict, deque
import openai
import yaml
import re
import time


def compile_blacklisted_regex(words):
    if not words:
        # If no blacklisted words, compile an always-false regex
        return re.compile(r'(?!x)x')
    pattern = r"|".join(re.escape(w) for w in words)
    return re.compile(pattern, re.IGNORECASE)


class AIAutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Tracking user messages for spam detection
        self.user_message_count = defaultdict(lambda: deque(maxlen=10))
        
        # Tracks warnings and mutes
        self.user_warnings = defaultdict(int)
        self.user_mutes = defaultdict(int)
        
        # Configuration
        self.warning_threshold = 3
        self.spam_interval = 4
        self.spam_message_limit = 5
        self.mute_duration = 60
        self.warning_decay_seconds = 3600

        self.user_warning_timestamps = defaultdict(list)

        # Load config
        with open("config/config.yaml", "r") as f:
            config = yaml.safe_load(f)

        openai.api_key = config["OPENAI_API_KEY"]

        # Basic blacklisted words
        self.blacklisted_words = ["spamword1", "spamword2", "badword", "anotherbadword"]
        self.blacklist_pattern = compile_blacklisted_regex(self.blacklisted_words)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Only one on_message for everything:
        1) If it's a recognized command, run it and skip moderation checks.
        2) If not, do moderation checks, then run process_commands to handle unknown commands.
        """
        if message.author.bot or not message.guild:
            return

        # Check if this message is a recognized command
        ctx = await self.bot.get_context(message)
        if ctx.command is not None:
            # It's a valid command => run it immediately and skip moderation
            await self.bot.process_commands(message)
            return

        # ===== Moderation Checks (spam, blacklisted words, AI toxicity) =====
        if await self.detect_spam(message):
            await self.delete_recent_messages(message.channel, message.author, 10)
            await self.issue_warning(message, "Please stop spamming!")
            return

        if self.blacklist_pattern.search(message.content):
            await message.delete()
            await self.issue_warning(message, "Your message contained prohibited content.")
            return

        if await self.detect_toxicity(message):
            await message.delete()
            await self.issue_warning(message, "Please maintain a respectful tone.")
            return

        # If it's not a recognized command and passes moderation, process commands
        # for unrecognized commands or other command checks.
        await self.bot.process_commands(message)

    async def detect_spam(self, message):
        now = time.time()
        user_id = message.author.id
        self.user_message_count[user_id].append(now)

        # Remove old timestamps outside spam_interval
        while self.user_message_count[user_id] and (now - self.user_message_count[user_id][0]) > self.spam_interval:
            self.user_message_count[user_id].popleft()

        return len(self.user_message_count[user_id]) >= self.spam_message_limit

    async def detect_toxicity(self, message):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",  # or "gpt-4"
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
                temperature=0
            )
            reply = response['choices'][0]['message']['content'].strip().lower()
            return reply.startswith("yes")
        except Exception as e:
            print(f"Toxicity detection error: {e}")
            return False

    async def issue_warning(self, message, reason):
        user_id = message.author.id
        self.decay_warnings(user_id)

        self.user_warnings[user_id] += 1
        current_warning_count = self.user_warnings[user_id]

        self.user_warning_timestamps[user_id].append((current_warning_count, time.time()))

        warning_msg = await message.channel.send(
            f"{message.author.mention}, {reason} (Warning #{current_warning_count})"
        )
        await asyncio.sleep(3)
        await warning_msg.delete()

        if current_warning_count >= self.warning_threshold:
            await self.mute_user(message)

    def decay_warnings(self, user_id):
        now = time.time()
        self.user_warning_timestamps[user_id] = [
            (count, tstamp) for (count, tstamp) in self.user_warning_timestamps[user_id]
            if (now - tstamp) < self.warning_decay_seconds
        ]
        self.user_warnings[user_id] = len(self.user_warning_timestamps[user_id])

    async def mute_user(self, message):
        guild = message.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")

        if not mute_role:
            mute_role = await guild.create_role(name="Muted")
            for channel in guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        if mute_role in message.author.roles:
            return

        await message.author.add_roles(mute_role)
        self.user_mutes[message.author.id] += 1

        mute_msg = await message.channel.send(
            f"{message.author.mention} has been muted due to repeated violations."
        )

        await asyncio.sleep(self.mute_duration)
        await message.author.remove_roles(mute_role)
        await mute_msg.delete()

        unmute_msg = await message.channel.send(
            f"{message.author.mention} has been unmuted."
        )
        await asyncio.sleep(2)
        await unmute_msg.delete()

    async def delete_recent_messages(self, channel, author, limit):
        async for msg in channel.history(limit=limit):
            if msg.author == author:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def add_blacklist(self, ctx, *, word):
        self.blacklisted_words.append(word.lower())
        self.blacklist_pattern = compile_blacklisted_regex(self.blacklisted_words)
        await ctx.send(f"Added `{word}` to the blacklist.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def remove_blacklist(self, ctx, *, word):
        self.blacklisted_words = [w for w in self.blacklisted_words if w != word.lower()]
        self.blacklist_pattern = compile_blacklisted_regex(self.blacklisted_words)
        await ctx.send(f"Removed `{word}` from the blacklist.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def show_blacklist(self, ctx):
        embed = discord.Embed(title="Blacklisted Words", color=discord.Color.red())
        if self.blacklisted_words:
            embed.description = "\n".join([f"- {word}" for word in self.blacklisted_words])
        else:
            embed.description = "No blacklisted words."
        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def user_status(self, ctx, member: discord.Member):
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
        self.user_warnings[member.id] = 0
        self.user_warning_timestamps[member.id].clear()
        await ctx.send(f"Cleared all warnings for {member.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(AIAutoMod(bot))
