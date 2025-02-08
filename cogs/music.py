import os
import discord
from discord.ext import commands
from yt_dlp import YoutubeDL
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

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

YDL_OPTIONS = {
    'format': 'bestaudio[abr>=128]/bestaudio',
    'noplaylist': True
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2 -c:a pcm_s16le -b:a 256k -af aresample=resampler=soxr -loglevel error'
}

class MusicControlsView(discord.ui.View):
    """A Discord UI view with music control buttons."""
    def __init__(self, cog, ctx):
        super().__init__(timeout=300)
        self.cog = cog
        self.ctx = ctx

    def _in_same_channel(self, interaction: discord.Interaction) -> bool:
        if not self.ctx.author.voice:
            return False
        if not interaction.user.voice or interaction.user.voice.channel != self.ctx.author.voice.channel:
            return False
        return True

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_same_channel(interaction):
            await interaction.response.send_message("You must be in the same voice channel as the bot!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.skip(self.ctx)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_same_channel(interaction):
            await interaction.response.send_message("You must be in the same voice channel as the bot!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.pause(self.ctx)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_same_channel(interaction):
            await interaction.response.send_message("You must be in the same voice channel as the bot!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.resume(self.ctx)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_same_channel(interaction):
            await interaction.response.send_message("You must be in the same voice channel as the bot!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.stop(self.ctx)

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.success)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._in_same_channel(interaction):
            await interaction.response.send_message("You must be in the same voice channel as the bot!", ephemeral=True)
            return
        queue_embed = self.cog.generate_queue_embed(self.ctx.guild.id)
        await interaction.response.send_message(embed=queue_embed, ephemeral=True)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.saved_queues = {}  # New: Stores saved queues
        self.sp = sp_client

    async def ensure_voice(self, ctx):
        if not ctx.author.voice:
            await ctx.send("You need to join a voice channel first!")
            return False
        if ctx.guild.voice_client is None:
            await ctx.author.voice.channel.connect()
        return True

    def generate_queue_embed(self, guild_id):
        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())
        if guild_id in self.queues and self.queues[guild_id]:
            now_playing = self.queues[guild_id][0][1]
            embed.add_field(name="Now Playing", value=now_playing, inline=False)
            if len(self.queues[guild_id]) > 1:
                upcoming = "\n".join([f"{i+1}. {song[1]}" for i, song in enumerate(self.queues[guild_id][1:])])
                embed.add_field(name="Up Next", value=upcoming, inline=False)
            embed.set_footer(text=f"{len(self.queues[guild_id])} song(s) in the queue.")
        else:
            embed.description = "The queue is currently empty."
        return embed

    async def play_next(self, ctx):
        if ctx.guild.id in self.queues and self.queues[ctx.guild.id]:
            url, title = self.queues[ctx.guild.id].pop(0)
            ctx.guild.voice_client.play(
                discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS),
                after=lambda e: self.bot.loop.create_task(self.play_next(ctx))
            )
            now_playing_embed = discord.Embed(
                title="Now Playing",
                description=f"**{title}**",
                color=discord.Color.blue()
            )
            view = MusicControlsView(self, ctx)
            await ctx.send(embed=now_playing_embed, view=view)
        else:
            await ctx.send(embed=discord.Embed(
                description="The queue is now empty.",
                color=discord.Color.red()
            ))

    @commands.command()
    async def play(self, ctx, *, search: str):
        if not await self.ensure_voice(ctx):
            return

        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []

        # Handle Spotify
        if "open.spotify.com" in search and self.sp:
            # ... existing Spotify handling code ...

        # New: Handle YouTube playlists
        is_youtube = any(s in search for s in ['youtube.com', 'youtu.be'])
        if is_youtube and 'list=' in search:
            try:
                ydl_opts = YDL_OPTIONS.copy()
                ydl_opts['noplaylist'] = False
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(search, download=False)
                    if 'entries' in info:
                        added = 0
                        for entry in info['entries']:
                            if entry:
                                self.queues[ctx.guild.id].append((
                                    entry['url'],
                                    entry['title']
                                ))
                                added += 1
                        await ctx.send(f"Added {added} songs from YouTube playlist to queue!")
                        if not ctx.guild.voice_client.is_playing():
                            await self.play_next(ctx)
                        return
            except Exception as e:
                await ctx.send(f"Error processing YouTube playlist: {e}")
                return

        # Existing single video handling
        try:
            with YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]
            self.queues[ctx.guild.id].append((info['url'], info['title']))
            await ctx.send(f"Added **{info['title']}** to queue!")
            if not ctx.guild.voice_client.is_playing():
                await self.play_next(ctx)
        except Exception as e:
            await ctx.send(f"Error: {e}")

    # New: Save queue command
    @commands.command()
    async def savequeue(self, ctx, name: str):
        if ctx.guild.id not in self.queues or not self.queues[ctx.guild.id]:
            await ctx.send("Queue is empty!")
            return
            
        if ctx.guild.id not in self.saved_queues:
            self.saved_queues[ctx.guild.id] = {}
            
        self.saved_queues[ctx.guild.id][name] = self.queues[ctx.guild.id].copy()
        await ctx.send(f"Queue saved as **{name}**!")

    # New: Load queue command
    @commands.command()
    async def loadqueue(self, ctx, name: str):
        try:
            self.queues[ctx.guild.id] = self.saved_queues[ctx.guild.id][name].copy()
            await ctx.send(f"Loaded queue **{name}**!")
            if not ctx.guild.voice_client.is_playing():
                await self.play_next(ctx)
        except KeyError:
            await ctx.send("Queue not found!")

    # ... existing skip, pause, resume, stop commands ...

async def setup(bot):
    await bot.add_cog(Music(bot))