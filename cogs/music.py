import os
import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp import YoutubeDL
import asyncio
import random
from collections import deque

# Spotify configuration (if needed)
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }]
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues = {}
        self.now_playing = {}
        self.volume = 0.75

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
            vc = interaction.guild.voice_client
            if vc and vc.is_connected():
                if self.queues.get(interaction.guild.id) and self.queues[interaction.guild.id]:
                    url, title = self.queues[interaction.guild.id].popleft()
                    self.now_playing[interaction.guild.id] = title
                    
                    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
                    source = discord.PCMVolumeTransformer(source, self.volume)

                    def after_playback(error):
                        if error:
                            print(f"Playback error: {error}")
                        coro = self.play_next(interaction)
                        fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
                        try:
                            fut.result()
                        except:
                            pass

                    vc.play(source, after=after_playback)
                    await self.send_now_playing(interaction, title, url)
                else:
                    await vc.disconnect()
                    self.queues.pop(interaction.guild.id, None)
                    self.now_playing.pop(interaction.guild.id, None)
        except Exception as e:
            print(f"Error in play_next: {e}")

    async def send_now_playing(self, interaction, title, url):
        try:
            embed = discord.Embed(
                title="🎶 Now Playing",
                description=f"[{title}]({url})",
                color=discord.Color.blurple()
            )
            await interaction.channel.send(embed=embed)
        except Exception as e:
            print(f"Error sending now playing: {e}")

    @app_commands.command(name="play", description="Play music from YouTube or Spotify")
    @app_commands.describe(query="Song name, URL, or Spotify link")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        
        if not await self.ensure_voice(interaction):
            return

        try:
            guild_id = interaction.guild.id
            if guild_id not in self.queues:
                self.queues[guild_id] = deque()

            with YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                if not info or 'entries' not in info or not info['entries']:
                    await interaction.followup.send("❌ No results found!", ephemeral=True)
                    return
                
                entry = info['entries'][0]
                self.queues[guild_id].append((entry['url'], entry['title']))
                await interaction.followup.send(f"✅ Added **{entry['title']}** to queue!")

            vc = interaction.guild.voice_client
            if not vc.is_playing():
                await self.play_next(interaction)
                
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)[:150]}", ephemeral=True)
            print(f"Play error: {e}")

    @app_commands.command(name="skip", description="Skip current song")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped current song")
            await self.play_next(interaction)
        else:
            await interaction.response.send_message("❌ Nothing is playing", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))