import discord
from discord.ext import commands
import asyncio
from collections import defaultdict
import openai
import yaml

class AIAutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_message_count = defaultdict(list)  # Tracks message timestamps per user
        self.user_warnings = defaultdict(int)  # Tracks warnings per user
        self.user_mutes = defaultdict(int)  # Tracks mutes per user
        self.blacklisted_words = ["spamword1", "spamword2"]  # Example words to block
        self.warning_threshold = 5  # Warnings before a mute
        self.spam_interval = 5  # Reduced timeframe for detecting spam (seconds)

        # Load configuration
        with open("config/config.yaml", "r") as config_file:
            config = yaml.safe_load(config_file)

        # Set your OpenAI API key
        openai.api_key = config["OPENAI_API_KEY"]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:  # Ignore bot messages
            return

        # Spam detection
        if await self.detect_spam(message):
            await self.delete_recent_messages(message.channel, message.author, 12)
            await self.issue_warning(message, "please stop spamming!")
            return

        # Blacklisted words detection
        if any(word in message.content.lower() for word in self.blacklisted_words):
            await message.delete()
            await self.issue_warning(message, "your message contained prohibited content.")
            return

        # Toxicity detection (using OpenAI API)
        if await self.detect_toxicity(message):
            await message.delete()
            await self.issue_warning(message, "please maintain a respectful tone.")
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
                model="gpt-4-turbo",
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

    async def delete_recent_messages(self, channel, author, limit):
        """Delete the recent messages from a specific user."""
        async for msg in channel.history(limit=limit):
            if msg.author == author:
                await msg.delete()

    async def issue_warning(self, message, warning_text):
        """Issue a warning, delete it after a delay, and handle mutes if needed."""
        self.user_warnings[message.author.id] += 1
        warning_msg = await message.channel.send(f"{message.author.mention}, {warning_text} This is warning #{self.user_warnings[message.author.id]}.")
        await asyncio.sleep(2)  # Auto-remove the warning after 2 seconds
        await warning_msg.delete()

        # Mute the user if warnings exceed a threshold
        if self.user_warnings[message.author.id] >= 3:  # Mute after 3 warnings
            await self.mute_user(message)

    async def mute_user(self, message):
        """Mute the user temporarily."""
        guild = message.guild
        mute_role = discord.utils.get(guild.roles, name="Muted")

        if not mute_role:
            # Create a Muted role if it doesn't exist
            mute_role = await guild.create_role(name="Muted")
            for channel in guild.channels:
                await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)

        # Assign the mute role
        await message.author.add_roles(mute_role)
        self.user_mutes[message.author.id] += 1
        mute_msg = await message.channel.send(f"{message.author.mention} has been muted due to repeated violations.")

        # Unmute after a delay
        await asyncio.sleep(60)  # Mute duration: 60 seconds
        await message.author.remove_roles(mute_role)
        await mute_msg.delete()  # Delete the mute message after the mute duration
        unmute_msg = await message.channel.send(f"{message.author.mention} has been unmuted.")
        await asyncio.sleep(2)  # Display the unmute message briefly
        await unmute_msg.delete()

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
        embed = discord.Embed(title="Blacklisted Words", color=discord.Color.red())

        if self.blacklisted_words:
            embed.description = "\n".join([f"- {word}" for word in self.blacklisted_words])
        else:
            embed.description = "No blacklisted words."

        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def user_status(self, ctx, member: discord.Member):
        """Check the number of warnings and mutes for a specific user."""
        warnings = self.user_warnings.get(member.id, 0)
        mutes = self.user_mutes.get(member.id, 0)
        embed = discord.Embed(title=f"User Status: {member.display_name}", color=discord.Color.blue())
        embed.add_field(name="Warnings", value=warnings, inline=False)
        embed.add_field(name="Mutes", value=mutes, inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AIAutoModCog(bot))
