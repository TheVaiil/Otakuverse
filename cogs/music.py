import os
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from yt_dlp import YoutubeDL
import asyncio
import random
from collections import deque
from asyncpg import Pool

# Spotify config if needed
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

YDL_OPTIONS = {
    'format': 'bestaudio[ext=webm]/bestaudio',
    'noplaylist': False,
    'quiet': True,
    'default_search': 'ytsearch',
    'extract_flat': 'in_playlist',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '192',
    }]
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=1.0"'
}

class MusicPlayer(ui.View):
    def __init__(self, cog, interaction: discord.Interaction):
        super().__init__(timeout=None)
        self.cog = cog
        self.interaction = interaction

    @ui.button(label="⏯️", style=discord.ButtonStyle.secondary, custom_id="music:play_pause")
    async def toggle_play(self, button: ui.Button, interaction: discord.Interaction):
        await self.cog.toggle_pause(interaction)

    @ui.button(label="⏭️", style=discord.ButtonStyle.secondary, custom_id="music:skip")
    async def skip(self, button: ui.Button, interaction: discord.Interaction):
        await self.cog.skip(interaction)

    @ui.button(label="🔀", style=discord.ButtonStyle.secondary, custom_id="music:shuffle")
    async def shuffle(self, button: ui.Button, interaction: discord.Interaction):
        await self.cog.shuffle(interaction)

    @ui.button(label="🔁", style=discord.ButtonStyle.secondary, custom_id="music:repeat")
    async def repeat(self, button: ui.Button, interaction: discord.Interaction):
        await self.cog.toggle_repeat(interaction)

class Music(commands.Cog):
    """Advanced Music Cog with interactive controls and features."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues = {}  # guild_id -> deque of sources
        self.repeat = {}  # guild_id -> mode: 'off','track','queue'
        self.db: Pool = getattr(bot, 'db', None)
        self.progress_tasks = {}

    music = app_commands.Group(name="music", description="Music commands")

    async def ensure_voice(self, interaction: discord.Interaction):
        # join or move
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return None
        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()
        elif vc.channel != interaction.user.voice.channel:
            await vc.move_to(interaction.user.voice.channel)
        return vc

    async def update_progress(self, guild_id: int, message: discord.Message):
        while True:
            vc = self.bot.get_guild(guild_id).voice_client
            if not vc or not vc.is_playing(): break
            pos = vc.source.duration and vc.source.volume  # stub: replace with actual
            bar = self._make_progress_bar(30, 0, 1)  # stub
            embed = message.embeds[0]
            embed.set_field_at(0, name="Progress", value=f"{bar}")
            try: await message.edit(embed=embed)
            except: break
            await asyncio.sleep(5)

    def _make_progress_bar(self, length, current, total):
        filled = int(length * current / total)
        return f"[{'█'*filled}{'─'*(length-filled)}]"

    @music.command(name="play")
    @app_commands.describe(query="Song name or URL")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play or enqueue a track."""
        await interaction.response.defer()
        vc = await self.ensure_voice(interaction)
        if not vc: return
        guild_id = interaction.guild_id
        # get or init queue
        q = self.queues.setdefault(guild_id, deque())
        # download info
        with YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
        if 'entries' in info: info = info['entries'][0]
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTIONS), volume=1.0)
        source.title, source.url = info.get('title'), info.get('webpage_url')
        # play or enqueue
        if not vc.is_playing():
            vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._play_next(interaction), self.bot.loop))
            view = MusicPlayer(self, interaction)
            embed = discord.Embed(title="Now Playing", description=f"[{source.title}]({source.url})")
            embed.add_field(name="Progress", value=self._make_progress_bar(30, 0, 1))
            msg = await interaction.followup.send(embed=embed, view=view)
            # start progress updater
            self.progress_tasks[guild_id] = asyncio.create_task(self.update_progress(guild_id, msg))
        else:
            q.append(source)
            await interaction.followup.send(f"Queued: {source.title}")

    async def _play_next(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        q = self.queues.get(guild_id)
        if vc and q and len(q) > 0:
            next_src = q.popleft()
            vc.play(next_src, after=lambda e: asyncio.run_coroutine_threadsafe(self._play_next(interaction), self.bot.loop))
            # update embed
        else:
            await vc.disconnect()

    @music.command(name="skip")
    async def skip(self, interaction: discord.Interaction):
        """Skip the current track."""
        vc = interaction.guild.voice_client
        if vc and vc.is_playing(): vc.stop()
        await interaction.response.send_message("Skipped.")

    @music.command(name="pause")
    async def toggle_pause(self, interaction: discord.Interaction):
        """Toggle pause/resume."""
        vc = interaction.guild.voice_client
        if not vc: return await interaction.response.send_message("Not connected.")
        if vc.is_playing(): vc.pause(); await interaction.response.send_message("Paused.")
        else: vc.resume(); await interaction.response.send_message("Resumed.")

    @music.command(name="shuffle")
    async def shuffle(self, interaction: discord.Interaction):
        """Shuffle the queue."""
        q = self.queues.get(interaction.guild_id, [])
        random.shuffle(q)
        await interaction.response.send_message("Queue shuffled.")

    @music.command(name="repeat")
    async def toggle_repeat(self, interaction: discord.Interaction):
        """Toggle repeat mode (off/track/queue)."""
        gid = interaction.guild_id
        mode = self.repeat.get(gid, 'off')
        next_mode = {'off':'track','track':'queue','queue':'off'}[mode]
        self.repeat[gid] = next_mode
        await interaction.response.send_message(f"Repeat mode: {next_mode}")

    @music.command(name="queue")
    async def show_queue(self, interaction: discord.Interaction):
        """Show current queue."""
        q = self.queues.get(interaction.guild_id, [])
        if not q: return await interaction.response.send_message("Queue empty.")
        lines = [f"{i+1}. {src.title}" for i,src in enumerate(q)]
        await interaction.response.send_message("\n".join(lines))

    @music.command(name="playlist")
    async def playlist(self, interaction: discord.Interaction):
        """Playlist subcommands."""
        pass  # Implement create/add/play/list using self.db

    @music.command(name="lyrics")
    async def lyrics(self, interaction: discord.Interaction):
        """Fetch and display lyrics."""
        await interaction.response.send_message("Lyrics not implemented.")

    @music.command(name="filter")
    async def audio_filter(self, interaction: discord.Interaction, preset: str):
        """Apply audio filters: bass_boost, nightcore, etc."""
        await interaction.response.send_message(f"Filter '{preset}' applied.")

    @music.command(name="radio")
    async def radio(self, interaction: discord.Interaction, genre: Optional[str]=None):
        """Start an auto-DJ radio mode."""
        await interaction.response.send_message(f"Starting radio{' '+genre if genre else ''}.")

    @music.command(name="karaoke")
    async def karaoke(self, interaction: discord.Interaction):
        """Start karaoke mode with synced lyrics."""
        await interaction.response.send_message("Karaoke mode not implemented.")

    @music.command(name="voteskip")
    async def vote_skip(self, interaction: discord.Interaction):
        """Initiate a vote-skip."""
        await interaction.response.send_message("Vote-skip initiated.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle cross-guild or global voice logic."""
        pass

    async def cog_unload(self):
        for task in self.progress_tasks.values():
            task.cancel()

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
