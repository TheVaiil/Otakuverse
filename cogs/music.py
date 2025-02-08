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

# Updated yt_dlp options for better quality streams
YDL_OPTIONS = {
    'format': 'bestaudio[abr>=128]/bestaudio',
    'noplaylist': True
}

# Enhanced FFmpeg options:
#   - '-vn': disable video
#   - '-ar 48000': force a 48kHz sample rate (Discord’s native rate)
#   - '-ac 2': force stereo
#   - '-c:a pcm_s16le': force raw 16-bit PCM output
#   - '-b:a 256k': set audio bitrate to 256kbps (if available)
#   - '-af aresample=resampler=soxr': use the soxr resampler for higher-quality resampling
#   - '-loglevel error': suppress extra FFmpeg logging
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2 -c:a pcm_s16le -b:a 256k -af aresample=resampler=soxr -loglevel error'
}

class MusicControlsView(discord.ui.View):
    """A Discord UI view with music control buttons."""
    def __init__(self, cog, ctx):
        super().__init__(timeout=300)  # 5 minutes timeout (adjust as needed)
        self.cog = cog
        self.ctx = ctx

    def _in_same_channel(self, interaction: discord.Interaction) -> bool:
        """Ensure the interacting user is in the same voice channel as the command author."""
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
        self.queues = {}  # Dictionary to hold song queues per guild
        self.sp = sp_client  # Spotify client (if available)

    async def ensure_voice(self, ctx):
        """Ensure the command user is in a voice channel and connect if necessary."""
        if not ctx.author.voice:
            await ctx.send("You need to join a voice channel first!")
            return False
        if ctx.guild.voice_client is None:
            await ctx.author.voice.channel.connect()
        return True

    def generate_queue_embed(self, guild_id):
        """Generate an embed that shows the current song queue."""
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
        """Play the next song in the queue (if any) and update controls."""
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
            await ctx.send(embed=self.generate_queue_embed(ctx.guild.id))
        else:
            await ctx.send(embed=discord.Embed(
                description="The queue is now empty.",
                color=discord.Color.red()
            ))

    @commands.command()
    async def play(self, ctx, *, search: str):
        """
        Play a song or add it to the queue.
        Supports Spotify links:
          • For a Spotify track URL, fetches track details.
          • For a Spotify playlist URL, queues all tracks.
        """
        if not await self.ensure_voice(ctx):
            return

        # Ensure the guild has a queue
        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []

        # Check for Spotify links (if Spotify support is available)
        if "open.spotify.com" in search and self.sp:
            if "track" in search:
                try:
                    track = self.sp.track(search)
                    title = f"{track['name']} - {', '.join(artist['name'] for artist in track['artists'])}"
                    search_query = title
                except Exception as e:
                    await ctx.send(f"Error fetching Spotify track: {e}")
                    return
            elif "playlist" in search:
                try:
                    playlist = self.sp.playlist_tracks(search)
                    tracks_added = 0
                    for item in playlist['items']:
                        track = item['track']
                        title = f"{track['name']} - {', '.join(artist['name'] for artist in track['artists'])}"
                        with YoutubeDL(YDL_OPTIONS) as ydl:
                            info = ydl.extract_info(f"ytsearch:{title}", download=False)['entries'][0]
                        url = info['url']
                        self.queues[ctx.guild.id].append((url, title))
                        tracks_added += 1
                    await ctx.send(embed=discord.Embed(
                        description=f"Added {tracks_added} tracks from the Spotify playlist to the queue.",
                        color=discord.Color.green())
                    )
                    if not ctx.guild.voice_client.is_playing():
                        await self.play_next(ctx)
                    return
                except Exception as e:
                    await ctx.send(f"Error fetching Spotify playlist: {e}")
                    return
            else:
                search_query = search
        else:
            search_query = search

        # For non-Spotify queries or fallback
        try:
            with YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(f"ytsearch:{search_query}", download=False)['entries'][0]
            url = info['url']
            title = info['title']
        except Exception as e:
            await ctx.send(f"Error fetching video: {e}")
            return

        self.queues[ctx.guild.id].append((url, title))
        await ctx.send(embed=discord.Embed(
            description=f"Added to queue: **{title}**",
            color=discord.Color.green())
        )
        if not ctx.guild.voice_client.is_playing():
            await self.play_next(ctx)

    @commands.command()
    async def skip(self, ctx):
        """Skip the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
            ctx.guild.voice_client.stop()
            await ctx.send(embed=discord.Embed(
                description="Skipped the song.",
                color=discord.Color.orange())
            )
        else:
            await ctx.send(embed=discord.Embed(
                description="Nothing is playing.",
                color=discord.Color.red())
            )

    @commands.command()
    async def pause(self, ctx):
        """Pause the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
            ctx.guild.voice_client.pause()
            await ctx.send(embed=discord.Embed(
                description="Paused the song.",
                color=discord.Color.orange())
            )
        else:
            await ctx.send(embed=discord.Embed(
                description="Nothing is playing.",
                color=discord.Color.red())
            )

    @commands.command()
    async def resume(self, ctx):
        """Resume the current song."""
        if ctx.guild.voice_client and ctx.guild.voice_client.is_paused():
            ctx.guild.voice_client.resume()
            await ctx.send(embed=discord.Embed(
                description="Resumed the song.",
                color=discord.Color.green())
            )
        else:
            await ctx.send(embed=discord.Embed(
                description="Nothing is paused.",
                color=discord.Color.red())
            )

    @commands.command()
    async def queue(self, ctx):
        """Show the current song queue."""
        await ctx.send(embed=self.generate_queue_embed(ctx.guild.id))

    @commands.command()
    async def stop(self, ctx):
        """Stop playback, clear the queue, and disconnect from voice."""
        if ctx.guild.voice_client:
            self.queues[ctx.guild.id] = []
            await ctx.guild.voice_client.disconnect()
            await ctx.send(embed=discord.Embed(
                description="Stopped playback and disconnected.",
                color=discord.Color.red())
            )

async def setup(bot):
    await bot.add_cog(Music(bot))
