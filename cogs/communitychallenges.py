import discord
import json
import asyncio
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from typing import Optional, Literal

class CommunityChallenges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_challenges = self.load_challenges()
        self.challenge_cleanup.start()

    def load_challenges(self):
        try:
            with open("challenges.json", "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_challenges(self):
        with open("challenges.json", "w") as f:
            json.dump(self.active_challenges, f, indent=4)

    @tasks.loop(minutes=5, reconnect=True)
    async def challenge_cleanup(self):
        now = datetime.utcnow().timestamp()
        expired = [guild_id for guild_id, challenge in self.active_challenges.items() if challenge['end_time'] <= now]
        
        for guild_id in expired:
            await self.send_challenge_recap(guild_id)
            del self.active_challenges[guild_id]
        
        self.save_challenges()
    
    async def send_challenge_recap(self, guild_id: int):
        challenge = self.active_challenges.get(str(guild_id))
        if not challenge:
            return

        channel = self.bot.get_channel(challenge['channel_id'])
        if channel:
            embed = self.create_leaderboard_embed(challenge)
            await channel.send(embed=embed)

    @app_commands.command(name="start_challenge", description="Start a new community challenge")
    @app_commands.default_permissions(manage_guild=True)
    async def start_challenge(self, interaction: discord.Interaction, challenge_type: Literal["readathon", "watchparty", "trivia"], duration: str, goal: Optional[int] = None, name: str = "Community Challenge"):
        try:
            end_time = datetime.utcnow() + self.parse_duration(duration)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        self.active_challenges[str(interaction.guild.id)] = {
            "name": name,
            "type": challenge_type,
            "goal": goal,
            "end_time": end_time.timestamp(),
            "channel_id": interaction.channel.id,
            "participants": {}
        }
        self.save_challenges()

        embed = self.create_challenge_embed(self.active_challenges[str(interaction.guild.id)])
        await interaction.response.send_message(embed=embed)
        await asyncio.create_task(self.schedule_recap(interaction.guild.id, (end_time - datetime.utcnow()).total_seconds()))
    
    async def schedule_recap(self, guild_id: int, delay: float):
        await asyncio.sleep(delay)
        if str(guild_id) in self.active_challenges:
            await self.send_challenge_recap(guild_id)

    @staticmethod
    def parse_duration(duration: str) -> timedelta:
        units = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}
        
        if not duration[:-1].isdigit() or duration[-1] not in units:
            raise ValueError("Invalid format! Use formats like 7d, 24h, 30m, 60s")
        
        return timedelta(**{units[duration[-1]]: int(duration[:-1])})
    
    def generate_leaderboard(self, challenge: dict) -> str:
        participants = sorted(challenge['participants'].items(), key=lambda x: x[1]['progress'], reverse=True)[:10]
        if not participants:
            return "No participants yet!"
        return "\n".join(f"{idx + 1}. {self.bot.get_user(int(user_id)).display_name if self.bot.get_user(int(user_id)) else 'Unknown'} - {data['progress']}/{challenge['goal'] or '∞'}" for idx, (user_id, data) in enumerate(participants))[:1024]
    
    def create_leaderboard_embed(self, challenge: dict) -> discord.Embed:
        embed = discord.Embed(title=f"Challenge Complete: {challenge['name']}", color=0x00ff00)
        leaderboard = self.generate_leaderboard(challenge)
        embed.add_field(name="Final Leaderboard", value=leaderboard, inline=False)
        return embed
    
    def create_challenge_embed(self, challenge: dict) -> discord.Embed:
        embed = discord.Embed(title=f"New Challenge: {challenge['name']}", color=0x5865F2)
        embed.add_field(name="Type", value=challenge['type'].capitalize(), inline=True)
        embed.add_field(name="Ends In", value=f"<t:{int(challenge['end_time'])}:R>", inline=True)
        if challenge['goal']:
            embed.add_field(name="Goal", value=str(challenge['goal']), inline=False)
        embed.set_footer(text="Use /join_challenge to participate!")
        return embed
    
    def cog_unload(self):
        self.challenge_cleanup.cancel()
        self.save_challenges()

    @commands.Cog.listener()
    async def on_ready(self):
        if self.bot.tree:
            self.bot.tree.add_command(self.start_challenge)

async def setup(bot):
    await bot.add_cog(CommunityChallenges(bot))
