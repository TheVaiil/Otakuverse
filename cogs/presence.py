# cogs/presence.py
import random
import json
import discord
import aiohttp
from discord.ext import commands, tasks
from datetime import datetime
from zoneinfo import ZoneInfo

class Presence(commands.Cog):
    """
    A complex presence manager that cycles through different activity types
    and displays dynamic information.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        
        # Load configuration
        with open('config.json', 'r') as f:
            self.config = json.load(f)
        
        self.repo_path = self.config.get("presence_repo")
        self.stream_url = self.config.get("twitch_url")

        self.change_presence.start()

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.change_presence.cancel()
        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    async def get_github_stats(self):
        """Fetches stats for the configured repository from the GitHub API."""
        if not self.repo_path:
            return None
        
        url = f"https://api.github.com/repos/{self.repo_path}"
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "stars": data.get("stargazers_count", 0),
                        "forks": data.get("forks_count", 0),
                        "issues": data.get("open_issues_count", 0),
                    }
        except Exception as e:
            print(f"Error fetching GitHub stats: {e}")
        return None

    @tasks.loop(minutes=15)
    async def change_presence(self):
        """The main background task to change the bot's presence."""
        
        # --- Define Day and Night Statuses ---
        # Each entry is a dictionary specifying the activity type and text
        
        DAY_STATUSES = [
            {"type": discord.ActivityType.watching, "text": "{guild_count} servers"},
            {"type": discord.ActivityType.listening, "text": "to /commands"},
            {"type": discord.ActivityType.playing, "text": "with the Discord API"},
            # Dynamic GitHub Statuses
            {"type": discord.ActivityType.watching, "text": "{stars} stars on GitHub"},
            {"type": discord.ActivityType.playing, "text": "with {forks} forks"},
            # Streaming Status
            {"type": discord.ActivityType.streaming, "text": "Live Development!"}
        ]

        NIGHT_STATUSES = [
            {"type": discord.ActivityType.watching, "text": "the moon 🌙"},
            {"type": discord.ActivityType.listening, "text": "to the sound of silence"},
            {"type": discord.ActivityType.playing, "text": "zZz..."}
        ]
        
        # Determine if it's day or night (e.g., 11 PM to 7 AM is night)
        # Using a timezone-aware datetime object
        now = datetime.now(ZoneInfo("Europe/Copenhagen"))
        
        if 23 <= now.hour or now.hour <= 7:
            chosen_list = NIGHT_STATUSES
        else:
            chosen_list = DAY_STATUSES

        presence_data = random.choice(chosen_list)
        activity_type = presence_data["type"]
        text_template = presence_data["text"]
        
        # Fetch dynamic data if needed
        github_stats = None
        if "{" in text_template:
            github_stats = await self.get_github_stats()
            
        # Format the text with live data
        formatted_text = text_template.format(
            guild_count=len(self.bot.guilds),
            user_count=len(self.bot.users),
            stars=github_stats.get("stars", 0) if github_stats else 0,
            forks=github_stats.get("forks", 0) if github_stats else 0,
            issues=github_stats.get("issues", 0) if github_stats else 0
        )
        
        # Create the specific activity object
        if activity_type == discord.ActivityType.streaming:
            activity = discord.Streaming(name=formatted_text, url=self.stream_url)
        elif activity_type == discord.ActivityType.playing:
            activity = discord.Game(name=formatted_text)
        else: # For watching, listening, etc.
            activity = discord.Activity(type=activity_type, name=formatted_text)
            
        await self.bot.change_presence(activity=activity)
        print(f"Presence updated to: {activity_type.name.capitalize()} {formatted_text}")

    @change_presence.before_loop
    async def before_change_presence(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Presence(bot))