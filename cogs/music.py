import os
import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp import YoutubeDL
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import asyncio
import random
from collections import deque
from typing import Literal

# Spotify configuration
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
sp_client = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET
)) if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET else None

YDL_OPTIONS = {
    'format': 'bestaudio[ext=webm]/bestaudio',
    'noplaylist': False,
    'quiet': True,
    'default_search': 'ytsearch',
    'extract_flat': 'in_playlist',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }]
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.75"'
}

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # {guild_id: deque}
        self.now_playing = {}
        self.volume = 0.75
        self.sp = sp_client

    async def ensure_voice(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You need to join a voice channel first!", ephemeral=True)
            return False
            
        vc = interaction.guild.voice_client
        if not vc:
            try:
                await interaction.user.voice.channel.connect()
            except Exception as e:
                await interaction.response.send_message(f"❌ Couldn't connect: {e}", ephemeral=True)
                return False
        elif vc.channel != interaction.user.voice.channel:
            await interaction.response.send_message("❌ I'm in another voice channel!", ephemeral=True)
            return False
            
        return True

    async def play_next(self, interaction: discord.Interaction):
        try:
            if not interaction.guild.voice_client or not self.queues.get(interaction.guild.id):
                return

            url, title = self.queues[interaction.guild.id].popleft()
            self.now_playing[interaction.guild.id] = title

            source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
            source = discord.PCMVolumeTransformer(source, self.volume)

            def after_playback(error):
                if error:
                    print(f"Playback error: {error}")
                asyncio.run_coroutine_threadsafe(self.play_next(interaction), self.bot.loop)

            interaction.guild.voice_client.play(source, after=after_playback)
            await self.send_now_playing(interaction, title, url)

        except Exception as e:
            await interaction.followup.send(f"❌ Playback error: {e}", ephemeral=True)

    async def send_now_playing(self, interaction, title, url):
        embed = discord.Embed(title="🎶 Now Playing", description=f"[{title}]({url})", color=discord.Color.blue())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="play", description="Play music from YouTube or Spotify")
    @app_commands.describe(query="Song name, URL, or Spotify link")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        
        if not await self.ensure_voice(interaction):
            return

        try:
            if interaction.guild.id not in self.queues:
                self.queues[interaction.guild.id] = deque()
                self.now_playing[interaction.guild.id] = None

            if not query.startswith(('http://', 'https://')):
                query = f"ytsearch:{query}"

            with YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(query, download=False)
                
                if 'entries' in info and info['entries']:
                    first_entry = info['entries'][0]
                    self.queues[interaction.guild.id].append((first_entry['url'], first_entry['title']))
                    await interaction.followup.send(f"✅ Added **{first_entry['title']}** to queue!")
                elif 'url' in info and 'title' in info:
                    self.queues[interaction.guild.id].append((info['url'], info['title']))
                    await interaction.followup.send(f"✅ Added **{info['title']}** to queue!")
                else:
                    await interaction.followup.send("❌ No valid results found.", ephemeral=True)
                    return

            if not interaction.guild.voice_client.is_playing():
                await self.play_next(interaction)
                
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="skip", description="Skip current song")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped current song")
            await self.play_next(interaction)
        else:
            await interaction.response.send_message("❌ Nothing is playing", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Music(bot))
