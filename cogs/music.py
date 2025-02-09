import os
import discord
from discord.ext import commands
from yt_dlp import YoutubeDL
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import asyncio

# Spotify configuration (if needed)
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET:
    sp_client = spotipy.Spotify(
        client_credentials_manager=SpotifyClientCredentials(
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET
        )
    )
else:
    sp_client = None  # Spotify support disabled if credentials are missing

# Updated yt_dlp options for better quality streams
YDL_OPTIONS = {
    'format': 'bestaudio[abr>=128]/bestaudio',
    'noplaylist': False  # Allow playlists
}

# Enhanced FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2 -b:a 256k -c:a libopus -loglevel error'
}

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # Dictionary to hold song queues per guild
        self.sp = sp_client  # Spotify client (if available)

    async def ensure_voice(self, ctx):
        """Ensure the command user is in a voice channel and connect if necessary."""
        if not ctx.author.voice:
            await ctx.send("You need to join a voice channel first!")
            return False
        if ctx.guild.voice_client is None:
            try:
                await ctx.author.voice.channel.connect()
            except discord.errors.ClientException:
                await ctx.send("I'm already connected to a voice channel!")
                return False
            except discord.errors.PermissionDenied:
                await ctx.send("I don't have permission to join that voice channel.")
                return False
            except Exception as e:
                await ctx.send(f"An error occurred while connecting: {e}")
                return False
        return True

    async def play_next(self, ctx):
        """Play the next song in the queue and ensure continuous playback."""
        if ctx.guild.id in self.queues and self.queues[ctx.guild.id]:
            url, title = self.queues[ctx.guild.id].pop(0)
            ctx.guild.voice_client.play(
                discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS),
                after=lambda e: self.bot.loop.call_soon_threadsafe(asyncio.create_task, self.play_next(ctx))
            )
            await ctx.send(embed=discord.Embed(description=f"Now playing: **{title}**", color=discord.Color.blue()))
        else:
            await asyncio.sleep(300)  # Wait 5 minutes before disconnecting
            if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
                await ctx.guild.voice_client.disconnect()

    @commands.command()
    async def play(self, ctx, *, search: str):
        """Play a song or playlist while starting playback immediately."""
        if not await self.ensure_voice(ctx):
            return

        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []

        try:
            with YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(search, download=False)
                if 'entries' in info:
                    first_song = info['entries'][0]
                    self.queues[ctx.guild.id].append((first_song['url'], first_song['title']))
                    await ctx.send(embed=discord.Embed(description=f"Now playing: **{first_song['title']}**", color=discord.Color.blue()))
                    
                    if not ctx.guild.voice_client.is_playing():
                        await self.play_next(ctx)
                    
                    for entry in info['entries'][1:]:
                        self.queues[ctx.guild.id].append((entry['url'], entry['title']))
                    await ctx.send(embed=discord.Embed(description=f"Added {len(info['entries'])} songs to queue!", color=discord.Color.green()))
                else:
                    self.queues[ctx.guild.id].append((info['url'], info['title']))
                    await ctx.send(embed=discord.Embed(description=f"Added to queue: **{info['title']}**", color=discord.Color.green()))
        except Exception as e:
            await ctx.send(f"Error fetching video: {e}")
            return

        if ctx.guild.voice_client and not ctx.guild.voice_client.is_playing():
            await self.play_next(ctx)

    @commands.command()
    async def skip(self, ctx):
        """Skip the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
            ctx.guild.voice_client.stop()
            await ctx.send(embed=discord.Embed(description="Skipped the song.", color=discord.Color.orange()))
            if not self.queues[ctx.guild.id]:
                await ctx.guild.voice_client.disconnect()

    @commands.command()
    async def stop(self, ctx):
        """Stop playback, clear the queue, and disconnect from voice."""
        if ctx.guild.voice_client:
            self.queues[ctx.guild.id] = []
            await ctx.guild.voice_client.disconnect()
            await ctx.send(embed=discord.Embed(description="Stopped playback and disconnected.", color=discord.Color.red()))

    @commands.command()
    async def queue(self, ctx):
        """Display the current song queue."""
        if ctx.guild.id in self.queues and self.queues[ctx.guild.id]:
            queue_list = "\n".join([f"{i+1}. {song[1]}" for i, song in enumerate(self.queues[ctx.guild.id])])
            await ctx.send(f"Current Queue:\n{queue_list}")
        else:
            await ctx.send("The queue is empty.")

    @commands.command()
    async def spplay(self, ctx, *, track_name: str):
        """Search and play a song from Spotify."""
        if self.sp is None:
            await ctx.send("Spotify integration is disabled.")
            return
        results = self.sp.search(track_name, limit=1)
        track = results['tracks']['items'][0]
        url = f"https://open.spotify.com/track/{track['id']}"
        title = track['name']
        
        # Add the song to the queue and play it
        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []
        self.queues[ctx.guild.id].append((url, title))
        
        await ctx.send(embed=discord.Embed(description=f"Added to queue: **{title}**", color=discord.Color.green()))
        
        if not ctx.guild.voice_client.is_playing():
            await self.play_next(ctx)

async def setup(bot):
    await bot.add_cog(Music(bot))
