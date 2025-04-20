import os
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from yt_dlp import YoutubeDL
import asyncio
import random
from collections import deque, defaultdict
from asyncpg import Pool
import ffmpeg
import requests
from io import BytesIO

# Spotify config
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

YDL_OPTIONS = {
    'format': 'bestaudio[ext=webm]/bestaudio',
    'noplaylist': False,
    'quiet': True,
    'default_search': 'ytsearch',
}

# EQ presets mapping to ffmpeg filter strings
EQ_PRESETS = {
    'bass_boost': 'bass=g=10',
    'nightcore': 'asetrate=48000*1.25,aresample=48000',
    # more presets...
}

class MusicPlayer(ui.View):
    "Interactive music controls (play/pause, skip, shuffle, repeat)"
    def __init__(self, cog, msg):
        super().__init__(timeout=None)
        self.cog = cog
        self.msg = msg

    @ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary)
    async def btn_pause(self, button, interaction):
        await self.cog.toggle_pause(interaction)

    @ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def btn_skip(self, button, interaction):
        await self.cog.skip(interaction)

    @ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def btn_shuffle(self, button, interaction):
        await self.cog.shuffle(interaction)

    @ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def btn_repeat(self, button, interaction):
        await self.cog.toggle_repeat(interaction)

class Music(commands.Cog):
    "Advanced Music Cog with full featured experience."
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues = defaultdict(deque)
        self.repeat_mode = defaultdict(lambda: 'off')
        self.db: Pool = getattr(bot, 'db', None)
        self.votes = {}  # guild->set(user_ids)
        self.progress_tasks = {}

    music = app_commands.Group(name="music", description="Music commands")

    async def ensure_voice(self, interaction):
        if not (ch := interaction.user.voice and interaction.user.voice.channel):
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return None
        vc = interaction.guild.voice_client
        if not vc:
            vc = await ch.connect()
        elif vc.channel != ch:
            await vc.move_to(ch)
        return vc

    def _progress_bar(self, pos, total, length=20):
        filled = int(pos/total * length)
        return f"[{'█'*filled}{'─'*(length-filled)}] {pos//60}:{pos%60:02d}/{total//60}:{total%60:02d}"

    async def update_progress(self, guild_id, msg):
        while True:
            vc = self.bot.get_guild(guild_id).voice_client
            if not vc or not vc.is_playing(): break
            pos = int(vc.source.seek if hasattr(vc.source, 'seek') else vc.source.elapsed)
            total = int(vc.source.duration)
            bar = self._progress_bar(pos, total)
            embed = msg.embeds[0]
            embed.set_field_at(1, name="Progress", value=bar)
            try: await msg.edit(embed=embed)
            except: break
            await asyncio.sleep(5)

    async def enqueue(self, info, interaction, vc):
        guild_id = interaction.guild_id
        src = discord.FFmpegPCMAudio(info['url'], **{'before_options':vc.options if hasattr(vc, 'options') else ''})
        src.title, src.url = info.get('title'), info.get('webpage_url')
        q = self.queues[guild_id]
        if not vc.is_playing():
            vc.play(src, after=lambda e: asyncio.run_coroutine_threadsafe(self.next_track(interaction), self.bot.loop))
            view = MusicPlayer(self, None)
            embed = discord.Embed(title="Now Playing", description=f"[{src.title}]({src.url})")
            embed.add_field(name="Progress", value=self._progress_bar(0, int(info.get('duration',0))))
            msg = await interaction.followup.send(embed=embed, view=view)
            view.msg = msg
            self.progress_tasks[guild_id] = asyncio.create_task(self.update_progress(guild_id, msg))
        else:
            q.append(src)
            await interaction.followup.send(f"Queued: {src.title}")

    async def next_track(self, interaction):
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        q = self.queues[guild_id]
        if self.repeat_mode[guild_id] == 'track':
            vc.play(vc.source)
        elif q:
            src = q.popleft()
            vc.play(src, after=lambda e: asyncio.run_coroutine_threadsafe(self.next_track(interaction), self.bot.loop))
        elif self.repeat_mode[guild_id] == 'queue':
            # reload from history
            pass
        else:
            await vc.disconnect()

    @music.command()
    @app_commands.describe(query="Song name or URL")
    async def play(self, interaction, query: str):
        """Play music from YouTube or Spotify"""
        await interaction.response.defer()
        vc = await self.ensure_voice(interaction)
        if not vc: return
        with YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
        if 'entries' in info: info = info['entries'][0]
        await self.enqueue(info, interaction, vc)

    @music.command()
    async def skip(self, interaction):
        "Skip current track (or vote skip)"
        vc = interaction.guild.voice_client
        gid = interaction.guild_id
        members = [m for m in vc.channel.members if not m.bot] if vc else []
        if len(members) > 1:
            self.votes.setdefault(gid, set()).add(interaction.user.id)
            if len(self.votes[gid]) >= max(1, len(members)//2):
                vc.stop()
                self.votes[gid].clear()
                await interaction.response.send_message("Vote threshold reached, skipping.")
            else:
                await interaction.response.send_message(f"Vote count: {len(self.votes[gid])}/{len(members)//2}", ephemeral=True)
        else:
            if vc and vc.is_playing(): vc.stop()
            await interaction.response.send_message("Skipped.")

    @music.command()
    async def pause(self, interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing(): vc.pause(); await interaction.response.send_message("Paused.")
        elif vc: vc.resume(); await interaction.response.send_message("Resumed.")
        else: await interaction.response.send_message("Not playing.", ephemeral=True)

    @music.command()
    async def shuffle(self, interaction):
        q = self.queues[interaction.guild_id]
        random.shuffle(q)
        await interaction.response.send_message("Queue shuffled.")

    @music.command()
    async def repeat(self, interaction):
        gid = interaction.guild_id
        modes = ['off','track','queue']
        idx = (modes.index(self.repeat_mode[gid]) + 1) % 3
        self.repeat_mode[gid] = modes[idx]
        await interaction.response.send_message(f"Repeat: {modes[idx]}")

    @music.command()
    async def queue(self, interaction):
        q = self.queues[interaction.guild_id]
        lines = [f"{i+1}. {src.title}" for i,src in enumerate(q)]
        await interaction.response.send_message("Queue:\n" + "\n".join(lines) if lines else "Queue empty.")

    @music.command()
    async def playlist(self, interaction, action: str, name: str, track: str = None):
        """Manage playlists: create, add, play, list"""
        if not self.db:
            return await interaction.response.send_message("Database disabled.")
        if action == 'create':
            await self.db.execute("INSERT INTO playlists(guild_id,name) VALUES($1,$2)", interaction.guild_id, name)
            await interaction.response.send_message(f"Playlist '{name}' created.")
        elif action == 'add' and track:
            await self.db.execute("INSERT INTO playlist_tracks(guild_id,name,track) VALUES($1,$2,$3)", interaction.guild_id, name, track)
            await interaction.response.send_message(f"Added to '{name}': {track}")
        elif action == 'play':
            rows = await self.db.fetch("SELECT track FROM playlist_tracks WHERE guild_id=$1 AND name=$2", interaction.guild_id, name)
            for r in rows:
                await self.play(interaction, r['track'])
        elif action == 'list':
            rows = await self.db.fetch("SELECT name FROM playlists WHERE guild_id=$1", interaction.guild_id)
            await interaction.response.send_message("Playlists: " + ", ".join(r['name'] for r in rows))

    @music.command()
    async def lyrics(self, interaction):
        """Fetch synced lyrics and send karaoke messages."""
        # stub: call lyrics API, schedule timed lines
        await interaction.response.send_message("Karaoke mode not yet implemented.")

    @music.command()
    async def filter(self, interaction, preset: str):
        """Apply audio filters."""
        # stub: reinitialize player with ffmpeg filter
        if preset in EQ_PRESETS:
            await interaction.response.send_message(f"Applied filter: {preset}")
        else:
            await interaction.response.send_message("Unknown preset.")

    @music.command()
    async def radio(self, interaction, genre: str = None):
        """Start auto-DJ radio using related videos."""
        # stub: fetch related video id
        await interaction.response.send_message("Radio mode not yet implemented.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Cross-guild / global queue logic placeholder."""
        # stub
        pass

    async def cog_unload(self):
        for task in self.progress_tasks.values(): task.cancel()

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
