import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import asyncio
from typing import Literal, Optional

class CommunityChallenges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_challenges = {}
        
        # Updated safe config access
        bot_config = getattr(bot, "config", {})
        self.config = bot_config.get("community_challenges", {})
        self.cleanup_interval = 300  # 5 minutes
        
        # Start background tasks
        self.challenge_cleanup.start()

    def cog_unload(self):
        self.challenge_cleanup.cancel()

    @tasks.loop(seconds=300)
    async def challenge_cleanup(self):
        """Cleanup expired challenges"""
        now = datetime.utcnow()
        to_remove = []
        
        for guild_id, challenge in self.active_challenges.items():
            if challenge['end_time'] <= now:
                to_remove.append(guild_id)
                await self.send_challenge_recap(guild_id)
        
        for guild_id in to_remove:
            del self.active_challenges[guild_id]

    async def send_challenge_recap(self, guild_id: int):
        """Generate and send challenge recap"""
        challenge = self.active_challenges.get(guild_id)
        if not challenge:
            return
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        channel_id = self.config.get("announcement_channel")
        channel = guild.get_channel(channel_id) if channel_id else None
        
        if not channel:
            return
        
        embed = discord.Embed(
            title=f"Challenge Complete: {challenge['name']}",
            color=0x00ff00
        )
        
        leaderboard = self.generate_leaderboard(challenge)
        embed.add_field(
            name="Final Leaderboard",
            value=leaderboard[:1024],
            inline=False
        )
        
        await channel.send(embed=embed)

    @commands.group(invoke_without_command=True)
    async def challenge(self, ctx):
        """Manage community challenges"""
        await ctx.send_help(ctx.command)

    @challenge.command()
    @commands.has_permissions(manage_guild=True)
    async def start(self, ctx, 
                   challenge_type: Literal["readathon", "watchparty", "trivia"], 
                   duration: str,
                   goal: Optional[int] = None,
                   *, name: str = "Community Challenge"):
        """
        Start a new community challenge
        Example: !challenge start readathon 7d 30 "Manga Marathon"
        """
        try:
            delta = self.parse_duration(duration)
        except ValueError:
            return await ctx.send("Invalid duration format. Use formats like 7d, 24h, 30m")
        
        if ctx.guild.id in self.active_challenges:
            return await ctx.send("There's already an active challenge in this server!")
        
        end_time = datetime.utcnow() + delta
        
        self.active_challenges[ctx.guild.id] = {
            "type": challenge_type,
            "name": name,
            "goal": goal,
            "start_time": datetime.utcnow(),
            "end_time": end_time,
            "participants": {},
            "channel": ctx.channel.id
        }
        
        embed = self.create_challenge_embed(ctx.guild.id)
        await ctx.send(embed=embed)
        
        # Schedule automatic recap
        await self.schedule_recap(ctx.guild.id, delta.total_seconds())
        
        # Integrate with announcements system
        announcement_cog = self.bot.get_cog("Announcements")
        if announcement_cog:
            await ctx.invoke(announcement_cog.announce, 
                            f"New Challenge Started: {name}!",
                            f"Type: {challenge_type}\nDuration: {duration}\nGoal: {goal or 'N/A'}")

    @challenge.command()
    async def join(self, ctx):
        """Join the active challenge"""
        challenge = self.active_challenges.get(ctx.guild.id)
        if not challenge:
            return await ctx.send("No active challenge in this server!")
        
        if ctx.author.id in challenge['participants']:
            return await ctx.send("You're already participating!")
        
        challenge['participants'][ctx.author.id] = {
            "progress": 0,
            "joined_at": datetime.utcnow()
        }
        
        await ctx.send(f"🎉 {ctx.author.mention} has joined the challenge!")

    @challenge.command()
    async def progress(self, ctx):
        """Check your challenge progress"""
        challenge = self.active_challenges.get(ctx.guild.id)
        if not challenge:
            return await ctx.send("No active challenge in this server!")
        
        participant = challenge['participants'].get(ctx.author.id)
        if not participant:
            return await ctx.send("You're not participating in the current challenge!")
        
        embed = discord.Embed(
            title=f"Challenge Progress: {challenge['name']}",
            color=0x7289da
        )
        
        progress = participant['progress']
        goal = challenge['goal']
        
        if goal:
            percent = (progress / goal) * 100
            embed.add_field(
                name="Progress",
                value=f"{progress}/{goal} ({percent:.1f}%)"
            )
        else:
            embed.add_field(
                name="Progress",
                value=str(progress)
            )
        
        await ctx.send(embed=embed)

    @commands.command()
    async def logchapter(self, ctx, count: int = 1):
        """Log chapters read for readathon challenges"""
        await self.update_progress(ctx, "readathon", count)

    @commands.command()
    async def logepisode(self, ctx, count: int = 1):
        """Log episodes watched for watchparty challenges"""
        await self.update_progress(ctx, "watchparty", count)

    async def update_progress(self, ctx, challenge_type: str, amount: int):
        challenge = self.active_challenges.get(ctx.guild.id)
        if not challenge or challenge['type'] != challenge_type:
            return
        
        participant = challenge['participants'].get(ctx.author.id)
        if not participant:
            return await ctx.send("You haven't joined this challenge!")
        
        challenge['participants'][ctx.author.id]["progress"] += amount
        await ctx.message.add_reaction("✅")
        
        # Check goal achievement
        if challenge['goal'] and participant['progress'] >= challenge['goal']:
            await ctx.send(f"🏆 {ctx.author.mention} has completed the challenge goal!")
            await self.grant_reward(ctx.author)

    def create_challenge_embed(self, guild_id: int) -> discord.Embed:
        challenge = self.active_challenges[guild_id]
        embed = discord.Embed(
            title=challenge['name'],
            description=f"**Type**: {challenge['type'].capitalize()}\n"
                       f"**Ends**: <t:{int(challenge['end_time'].timestamp())}:R>",
            color=0x5865F2
        )
        
        if challenge['goal']:
            embed.add_field(name="Server Goal", value=str(challenge['goal']))
        
        embed.set_footer(text="Use !challenge join to participate!")
        return embed

    def generate_leaderboard(self, challenge: dict) -> str:
        participants = sorted(
            challenge['participants'].items(),
            key=lambda x: x[1]['progress'],
            reverse=True
        )[:10]  # Top 10
        
        if not participants:
            return "No participants yet!"
        
        leaderboard = []
        for idx, (user_id, data) in enumerate(participants, 1):
            user = self.bot.get_user(user_id)
            display_name = user.display_name if user else "Unknown User"
            leaderboard.append(
                f"{idx}. {display_name} - {data['progress']}"
                f"{'/' + str(challenge['goal']) if challenge['goal'] else ''}"
            )
        
        return "\n".join(leaderboard)

    async def schedule_recap(self, guild_id: int, delay: float):
        await asyncio.sleep(delay)
        await self.send_challenge_recap(guild_id)

    @staticmethod
    def parse_duration(duration: str) -> timedelta:
        units = {
            "d": "days",
            "h": "hours",
            "m": "minutes",
            "s": "seconds"
        }
        
        unit = duration[-1]
        if unit not in units:
            raise ValueError("Invalid duration unit")
        
        value = int(duration[:-1])
        return timedelta(**{units[unit]: value})

    async def grant_reward(self, user: discord.Member):
        reward_role_id = self.config.get("reward_role")
        if not reward_role_id:
            return
        
        role = user.guild.get_role(reward_role_id)
        if not role:
            return
        
        try:
            await user.add_roles(role)
            await asyncio.sleep(self.config.get("reward_duration", 3600))
            await user.remove_roles(role)
        except discord.HTTPException as e:
            print(f"Error granting reward: {e}")

    @challenge.error
    async def challenge_error(self, ctx, error):
        if isinstance(error, commands.BadLiteralArgument):
            await ctx.send(f"Invalid challenge type! Valid types: {', '.join(error.literals)}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("You need manage server permissions to start challenges!")
        else:
            await ctx.send("An error occurred while processing the command.")

async def setup(bot):
    await bot.add_cog(CommunityChallenges(bot))