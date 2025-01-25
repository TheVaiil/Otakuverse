import discord
from discord.ext import commands
import asyncio
from collections import defaultdict
import openai

# Set your OpenAI API key
openai.api_key = "KEY!!!!!!"

class AIAutoModCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_message_count = defaultdict(list)  # Tracks message timestamps per user
        self.blacklisted_words = ["spamword1", "spamword2"]  # Example words to block
        self.warning_threshold = 5  # Warnings before a mute
        self.spam_interval = 5  # Timeframe for detecting spam (seconds)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:  # Ignore bot messages
            return

        # Spam detection
        if await self.detect_spam(message):
            await message.channel.send(f"{message.author.mention}, please stop spamming!!")
            await message.delete()
            return

        # Blacklisted words detection
        if any(word in message.content.lower() for word in self.blacklisted_words):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, your message contained prohibited content.")
            return

        # Toxicity detection (using OpenAI API)
        if await self.detect_toxicity(message):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, please maintain a respectful tone.")
            return

    async def detect_spam(self, message):
        """Detect if a user is spamming."""
        now = asyncio.get_event_loop().time()
        self.user_message_count[message.author.id].append(now)

        # Remove old messages outside the spam interval
        self.user_message_count[message.author.id] = [
            timestamp for timestamp in self.user_message_count[message.author.id]
            if now - timestamp <= self.spam_interval
        ]

        # If user exceeds spam threshold
        if len(self.user_message_count[message.author.id]) > self.warning_threshold:
            return True
        return False

    async def detect_toxicity(self, message):
        """Use AI to detect toxicity in a message."""
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a toxicity detection system."},
                    {"role": "user", "content": f"Is the following message toxic? '{message.content}'"}
                ]
            )
            reply = response['choices'][0]['message']['content'].strip().lower()
            return "yes" in reply  # Assume toxic if AI detects it
        except Exception as e:
            print(f"Toxicity detection error: {e}")
            return False

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def add_blacklist(self, ctx, *, word):
        """Add a word to the blacklist."""
        self.blacklisted_words.append(word.lower())
        await ctx.send(f"Added `{word}` to the blacklist.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def remove_blacklist(self, ctx, *, word):
        """Remove a word from the blacklist."""
        self.blacklisted_words = [w for w in self.blacklisted_words if w != word.lower()]
        await ctx.send(f"Removed `{word}` from the blacklist.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def show_blacklist(self, ctx):
        """Show the current blacklist."""
        await ctx.send(f"Blacklisted words: {', '.join(self.blacklisted_words)}")

async def setup(bot):
    await bot.add_cog(AIAutoModCog(bot))
