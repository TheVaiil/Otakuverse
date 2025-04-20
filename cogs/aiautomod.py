import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext.commands.cooldowns import CooldownMapping
import re
import asyncio
import openai
import logging
import json
import os
from collections import defaultdict, deque, OrderedDict
from datetime import datetime, timedelta

# Optional local detoxify fallback
try:
    from detoxify import Detoxify
    LOCAL_DETOX = Detoxify('original')
except ImportError:
    LOCAL_DETOX = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
MUTES_FILE = "mutes.json"

# Load or initialize config
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
else:
    CONFIG = {'default': {
        'spam_limit': 5,
        'spam_interval': 10,
        'warnings_before_mute': 3,
        'mute_duration': 15,
        'max_cache_size': 1000,
        'toxicity_cooldown': {'rate': 3, 'per': 60},
        'mod_log_channel': None,
        'whitelist_channels': []
    }, 'guild_overrides': {}}

# Helper to get guild-specific config
def get_cfg(guild_id: int):
    base = CONFIG.get('default', {})
    override = CONFIG.get('guild_overrides', {}).get(str(guild_id), {})
    cfg = base.copy()
    cfg.update(override)
    return cfg

# Save config helper
async def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(CONFIG, f, indent=2)

class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_tracker = defaultdict(lambda: deque(maxlen=get_cfg(0)['spam_limit']))
        self.user_warnings = defaultdict(lambda: defaultdict(int))
        self.blacklist = defaultdict(set)
        self.blacklist_pattern = {}
        self.blacklist_lock = asyncio.Lock()
        self.muted_users = {}
        self.metrics = defaultdict(int)

        # LRU cache for toxicity
        if not hasattr(self.bot, 'toxicity_cache'):
            self.bot.toxicity_cache = OrderedDict()

        # Cooldown mapping
        cd = get_cfg(0)['toxicity_cooldown']
        self.toxicity_cooldown = CooldownMapping.from_cooldown(
            cd['rate'], cd['per'], commands.BucketType.user)

        # Build automata if available
        self.aho_automatons = {}
        try:
            import ahocorasick
            self.ahocorasick_lib = ahocorasick
        except ImportError:
            self.ahocorasick_lib = None

        self.load_all_blacklists()
        self.load_mutes()
        self.check_mutes.start()
        self.cleanup_spam.start()

    # ------------- Configurable Blacklist Persistence -------------
    def load_all_blacklists(self):
        for guild in self.bot.guilds:
            path = f"blacklist_{guild.id}.txt"
            try:
                with open(path, 'r') as f:
                    self.blacklist[guild.id] = set(l.strip().lower() for l in f if l.strip())
            except FileNotFoundError:
                self.blacklist[guild.id] = set()
            self.update_blacklist_pattern(guild.id)

    async def save_blacklist(self, guild_id: int):
        path = f"blacklist_{guild_id}.txt"
        async with self.blacklist_lock:
            with open(path, 'w') as f:
                f.write("\n".join(sorted(self.blacklist[guild_id])))
        self.update_blacklist_pattern(guild_id)

    def update_blacklist_pattern(self, guild_id: int):
        words = self.blacklist[guild_id]
        if self.ahocorasick_lib and words:
            A = self.ahocorasick_lib.Automaton()
            for w in words:
                A.add_word(w, w)
            A.make_automaton()
            self.aho_automatons[guild_id] = A
            self.blacklist_pattern[guild_id] = None
        elif words:
            pat = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
            self.blacklist_pattern[guild_id] = re.compile(pat, re.IGNORECASE)
        else:
            self.blacklist_pattern[guild_id] = None

    # ------------- Mute Persistence with JSON -------------
    def load_mutes(self):
        try:
            with open(MUTES_FILE, 'r') as f:
                data = json.load(f)
                for gid, m in data.items():
                    self.muted_users[int(gid)] = {int(uid): datetime.fromisoformat(ts)
                                                   for uid, ts in m.items()}
        except Exception:
            self.muted_users = {}

    def save_mutes(self):
        data = {str(g): {str(u): t.isoformat() for u, t in m.items()}
                for g, m in self.muted_users.items()}
        with open(MUTES_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    # ------------- Background Tasks -------------
    @tasks.loop(seconds=30)
    async def check_mutes(self):
        now = datetime.utcnow()
        for gid, mutes in list(self.muted_users.items()):
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            for uid, ts in list(mutes.items()):
                if now >= ts:
                    role = discord.utils.get(guild.roles, name='Muted')
                    member = guild.get_member(uid)
                    if role and member:
                        await member.remove_roles(role, reason='Mute expired')
                        self.metrics['unmutes'] += 1
                        await self.log_action(guild, f'Unmuted {member.mention} (mute expired)')
                    del mutes[uid]
        self.save_mutes()

    @tasks.loop(hours=1)
    async def cleanup_spam(self):
        cutoff = datetime.utcnow() - timedelta(hours=24)
        for uid, dq in list(self.spam_tracker.items()):
            if not dq or dq[-1] < cutoff:
                del self.spam_tracker[uid]

    # ------------- Utility Helpers -------------
    async def log_action(self, guild: discord.Guild, text: str):
        cfg = get_cfg(guild.id)
        ch_id = cfg.get('mod_log_channel')
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch:
                embed = discord.Embed(description=text, timestamp=datetime.utcnow())
                await ch.send(embed=embed)

    async def send_dm(self, member: discord.Member, embed: discord.Embed):
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            logger.warning(f"Cannot DM {member}")

    # ------------- Modular Checks -------------
    async def check_spam(self, message):
        cfg = get_cfg(message.guild.id)
        if message.channel.id in cfg.get('whitelist_channels', []):
            return False
        now = datetime.utcnow()
        dq = self.spam_tracker[message.author.id]
        if not hasattr(dq, 'maxlen') or dq.maxlen != cfg['spam_limit']:
            self.spam_tracker[message.author.id] = deque(maxlen=cfg['spam_limit'])
            dq = self.spam_tracker[message.author.id]
        dq.append(now)
        if len(dq) == dq.maxlen and (now - dq[0]).total_seconds() < cfg['spam_interval']:
            await message.delete()
            self.metrics['spam_deleted'] += 1
            guild_id = message.guild.id
            self.user_warnings[guild_id][message.author.id] += 1
            warns = self.user_warnings[guild_id][message.author.id]
            if warns >= cfg['warnings_before_mute']:
                await self.apply_mute(message, cfg)
                del self.user_warnings[guild_id][message.author.id]
            else:
                await message.channel.send(
                    f"{message.author.mention}, please don't spam. Warnings: {warns}/{cfg['warnings_before_mute']}",
                    delete_after=10)
            return True
        return False

    async def check_blacklist(self, message):
        cfg = get_cfg(message.guild.id)
        if message.channel.id in cfg.get('whitelist_channels', []):
            return False
        gid = message.guild.id
        # Aho-corasick
        if self.ahocorasick_lib and gid in self.aho_automatons:
            for end_index, word in self.aho_automatons[gid].iter(message.content.lower()):
                await message.delete()
                self.metrics['blacklist_hits'] += 1
                await message.channel.send(
                    f"{message.author.mention}, your message contained a blacklisted word.", delete_after=10)
                return True
        patt = self.blacklist_pattern.get(gid)
        if patt and patt.search(message.content):
            await message.delete()
            self.metrics['blacklist_hits'] += 1
            await message.channel.send(
                f"{message.author.mention}, your message contained a blacklisted word.", delete_after=10)
            return True
        return False

    async def check_invites(self, message):
        # Block Discord invite links
        pat = re.compile(r"(?:https?://)?discord(?:\.gg|app\.com/invite)/\S+", re.IGNORECASE)
        if pat.search(message.content):
            await message.delete()
            self.metrics['invite_deleted'] += 1
            await message.channel.send(
                f"{message.author.mention}, invite links are not allowed.", delete_after=10)
            return True
        return False

    async def check_toxicity(self, message):
        cfg = get_cfg(message.guild.id)
        bucket = self.toxicity_cooldown.get_bucket(message)
        if bucket.update_rate_limit():
            return False
        key = f"{message.guild.id}:{message.content}"
        # Cached result
        if key in self.bot.toxicity_cache:
            is_toxic = self.bot.toxicity_cache[key]
            if is_toxic:
                await message.delete()
                self.metrics['toxicity_deleted'] += 1
                await message.channel.send(
                    f"{message.author.mention}, please maintain a respectful environment.", delete_after=10)
            return is_toxic
        try:
            resp = await openai.ChatCompletion.acreate(
                model="gpt-3.5-turbo",
                messages=[
                    {"role":"system","content":"Only respond with 'toxic' or 'safe'."},
                    {"role":"user","content":message.content}],
                timeout=10)
            verdict = resp.choices[0].message.content.strip().lower()
            is_toxic = (verdict == 'toxic')
        except Exception as e:
            logger.warning(f"Toxicity API error: {e}")
            # Fallback to local or blacklist
            self.metrics['api_fallbacks'] += 1
            if LOCAL_DETOX:
                tox_scores = LOCAL_DETOX.predict(message.content)
                is_toxic = tox_scores.get('toxicity', 0) > 0.5
            else:
                patt = self.blacklist_pattern.get(message.guild.id)
                is_toxic = bool(patt and patt.search(message.content))
        # Cache result
        self.bot.toxicity_cache[key] = is_toxic
        if len(self.bot.toxicity_cache) > get_cfg(message.guild.id)['max_cache_size']:
            self.bot.toxicity_cache.popitem(last=False)
        if is_toxic:
            await message.delete()
            self.metrics['toxicity_deleted'] += 1
            await message.channel.send(
                f"{message.author.mention}, please maintain a respectful environment.", delete_after=10)
            return True
        return False
        key = f"{message.guild.id}:{message.content}"
        if key in self.bot.toxicity_cache:
            return self.bot.toxicity_cache[key]
        try:
            resp = await openai.ChatCompletion.acreate(
                model="gpt-3.5-turbo",
                messages=[
                    {"role":"system","content":"Only respond with 'toxic' or 'safe'."},
                    {"role":"user","content":message.content}],
                timeout=10)
            verdict = resp.choices[0].message.content.strip().lower()
            is_toxic = (verdict == 'toxic')
        except Exception as e:
            logger.warning(f"Toxicity API error: {e}")
            # Fallback to local or blacklist
            self.metrics['api_fallbacks'] += 1
            if LOCAL_DETOX:
                tox_scores = LOCAL_DETOX.predict(message.content)
                is_toxic = tox_scores.get('toxicity', 0) > 0.5
            else:
                patt = self.blacklist_pattern.get(message.guild.id)
                is_toxic = bool(patt and patt.search(message.content))
        # Cache
        self.bot.toxicity_cache[key] = is_toxic
        if len(self.bot.toxicity_cache) > get_cfg(message.guild.id)['max_cache_size']:
            self.bot.toxicity_cache.popitem(last=False)
        if is_toxic:
            await message.delete()
            self.metrics['toxicity_deleted'] += 1
            await message.channel.send(
                f"{message.author.mention}, please maintain a respectful environment.", delete_after=10)
            return True
        return False

    async def apply_mute(self, message, cfg):
        # Check permissions
        guild = message.guild
        me = guild.me or guild.get_member(self.bot.user.id)
        if not me.guild_permissions.manage_roles:
            await message.channel.send("I lack permission to manage roles.")
            return
        role = discord.utils.get(guild.roles, name='Muted')
        if not role:
            role = await guild.create_role(name='Muted', reason='AutoMod role')
            for ch in guild.channels:
                await ch.set_permissions(role, send_messages=False,
                                         speak=False, add_reactions=False)
        member = message.author
        await member.add_roles(role, reason='AutoMod mute')
        unmute_at = datetime.utcnow() + timedelta(minutes=cfg['mute_duration'])
        self.muted_users[guild.id] = self.muted_users.get(guild.id, {})
        self.muted_users[guild.id][member.id] = unmute_at
        self.save_mutes()
        self.metrics['mutes'] += 1
        # DM
        embed = discord.Embed(title='You have been muted',
                              description=f'You have been muted in {guild.name} for {cfg["mute_duration"]} minutes.',
                              timestamp=datetime.utcnow())
        await self.send_dm(member, embed)
        # Log
        await self.log_action(guild, f'Muted {member.mention} for spam.')

    # ------------- Main Listener -------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        for check in (self.check_spam, self.check_blacklist,
                      self.check_invites, self.check_toxicity):
            try:
                if await check(message):
                    return
            except Exception as e:
                logger.error(f"Error in {check.__name__}: {e}", exc_info=True)

        # ------------- Slash Commands -------------
    @app_commands.command(name='blacklist_add', description='Add a word to the blacklist')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def blacklist_add(self, interaction: discord.Interaction, word: str):
        gid = interaction.guild_id
        w = word.lower().strip()
        self.blacklist[gid].add(w)
        await self.save_blacklist(gid)
        await interaction.response.send_message(f"Added '{w}' to blacklist.")

    @app_commands.command(name='blacklist_remove', description='Remove a word from the blacklist')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def blacklist_remove(self, interaction: discord.Interaction, word: str):
        gid = interaction.guild_id
        w = word.lower().strip()
        if w in self.blacklist[gid]:
            self.blacklist[gid].remove(w)
            await self.save_blacklist(gid)
            await interaction.response.send_message(f"Removed '{w}' from blacklist.")
        else:
            await interaction.response.send_message(f"'{w}' is not in the blacklist.")

    @app_commands.command(name='set_modlog', description='Set the mod-log channel')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_modlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        overrides = CONFIG.setdefault('guild_overrides', {}).setdefault(str(interaction.guild_id), {})
        overrides['mod_log_channel'] = channel.id
        await save_config()
        await interaction.response.send_message(f"Mod-log channel set to {channel.mention}.")

    @app_commands.command(name='whitelist_channel_add', description='Whitelist a channel from moderation')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def whitelist_channel_add(self, interaction: discord.Interaction, channel: discord.TextChannel):
        overrides = CONFIG.setdefault('guild_overrides', {}).setdefault(str(interaction.guild_id), {})
        overrides.setdefault('whitelist_channels', []).append(channel.id)
        await save_config()
        await interaction.response.send_message(f"Whitelist added {channel.mention}.")

    @app_commands.command(name='stats', description='Show AutoMod statistics')
    async def stats(self, interaction: discord.Interaction):
        m = self.metrics
        embed = discord.Embed(title='AutoMod Stats', timestamp=datetime.utcnow())
        for k, v in m.items():
            embed.add_field(name=k.replace('_', ' ').title(), value=str(v), inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
