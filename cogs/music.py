import discord
from discord.ext import commands
from yt_dlp import YoutubeDL

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # Song queues for each guild

    async def ensure_voice(self, ctx):
        """Ensure the bot is connected to the user's voice channel."""
        if not ctx.author.voice:
            await ctx.send("You need to join a voice channel first!")
            return False
        if ctx.guild.voice_client is None:
            await ctx.author.voice.channel.connect()
        return True

    def generate_queue_embed(self, guild_id):
        """Generate an embed to display the current queue."""
        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

        if guild_id in self.queues and self.queues[guild_id]:
            queue_list = "\n".join([f"{i+1}. {song[1]}" for i, song in enumerate(self.queues[guild_id])])
            embed.add_field(name="Now Playing", value=self.queues[guild_id][0][1], inline=False)
            embed.add_field(name="Up Next", value=queue_list, inline=False)
            embed.set_footer(text=f"{len(self.queues[guild_id])} songs in the queue.")
        else:
            embed.description = "The queue is currently empty."

        return embed

    @commands.command()
    async def play(self, ctx, *, search: str):
        """Play a song or add it to the queue."""
        if not await self.ensure_voice(ctx):
            return

        YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': True}
        FFMPEG_OPTIONS = {'options': '-vn'}

        with YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]
        url = info['url']
        title = info['title']

        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []

        self.queues[ctx.guild.id].append((url, title))
        await ctx.send(embed=discord.Embed(description=f"Added to queue: **{title}**", color=discord.Color.green()))

        if not ctx.guild.voice_client.is_playing():
            await self.play_next(ctx)

    async def play_next(self, ctx):
        """Play the next song in the queue."""
        if ctx.guild.id in self.queues and self.queues[ctx.guild.id]:
            url, title = self.queues[ctx.guild.id].pop(0)
            ctx.guild.voice_client.play(discord.FFmpegPCMAudio(url), after=lambda e: self.bot.loop.create_task(self.play_next(ctx)))
            await ctx.send(embed=discord.Embed(description=f"Now playing: **{title}**", color=discord.Color.blue()))

            # Display the updated queue
            await ctx.send(embed=self.generate_queue_embed(ctx.guild.id))
        else:
            await ctx.send(embed=discord.Embed(description="The queue is now empty.", color=discord.Color.red()))

    @commands.command()
    async def skip(self, ctx):
        """Skip the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
            ctx.guild.voice_client.stop()
            await ctx.send(embed=discord.Embed(description="Skipped the song.", color=discord.Color.orange()))
        else:
            await ctx.send(embed=discord.Embed(description="Nothing is playing.", color=discord.Color.red()))

    @commands.command()
    async def pause(self, ctx):
        """Pause the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
            ctx.guild.voice_client.pause()
            await ctx.send(embed=discord.Embed(description="Paused the song.", color=discord.Color.orange()))
        else:
            await ctx.send(embed=discord.Embed(description="Nothing is playing.", color=discord.Color.red()))

    @commands.command()
    async def resume(self, ctx):
        """Resume the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_paused():
            ctx.guild.voice_client.resume()
            await ctx.send(embed=discord.Embed(description="Resumed the song.", color=discord.Color.green()))
        else:
            await ctx.send(embed=discord.Embed(description="Nothing is paused.", color=discord.Color.red()))

    @commands.command()
    async def queue(self, ctx):
        """Show the current queue."""
        await ctx.send(embed=self.generate_queue_embed(ctx.guild.id))

    @commands.command()
    async def stop(self, ctx):
        """Stop playback and clear the queue."""
        if ctx.guild.voice_client:
            self.queues[ctx.guild.id] = []
            await ctx.guild.voice_client.disconnect()
            await ctx.send(embed=discord.Embed(description="Stopped playback and disconnected.", color=discord.Color.red()))

async def setup(bot):
    await bot.add_cog(Music(bot))
