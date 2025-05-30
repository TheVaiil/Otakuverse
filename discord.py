import os
import yaml
import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Set
from contextlib import suppress

import discord
from discord import app_commands, Intents, Object
from discord.ext import commands
from aiohttp import web
from pydantic import BaseModel, Field, ValidationError
import asyncpg

# Optional uvloop for performance
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logging.getLogger("discord_bot").info("Using uvloop for improved performance.")
except ImportError:
    logging.getLogger("discord_bot").info("uvloop not installed; using default asyncio loop.")

# Directories
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
COGS_DIR = BASE_DIR / "cogs"
PLUGINS_DIR = BASE_DIR / "plugins"
CONFIG_PATH = BASE_DIR / os.getenv("CONFIG_PATH", "config/config.yaml")
for d in (LOG_DIR, COGS_DIR, PLUGINS_DIR):
    d.mkdir(parents=True, exist_ok=True)
(PLUGINS_DIR / "__init__.py").touch(exist_ok=True)
(COGS_DIR / "__init__.py").touch(exist_ok=True) # Also good practice for cogs

# Logging setup
logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO) # Consider logging.DEBUG for more verbose dev output
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
for handler in (logging.StreamHandler(), logging.FileHandler(LOG_DIR / "bot.log")):
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Prometheus metrics definitions (optional)
try:
    from aioprometheus import Counter, Service
    metrics_enabled = True
except ImportError:
    logger.warning("aioprometheus not installed; metrics disabled.")
    metrics_enabled = False
    # Mock classes for when aioprometheus is not installed
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def inc(self, labels: Optional[dict] = None, value: float = 1.0): pass # Match signature
    class Service:
        def register(self, *args, **kwargs): pass
        async def handle(self, request):
            return web.Response(text="Metrics disabled (aioprometheus not installed).")

METRICS = {
    'spam_deleted': Counter('spam_deleted_total', 'Total spam deletions'),
    'blacklist_hits': Counter('blacklist_hits_total', 'Total blacklist hits'),
    'invite_deleted': Counter('invite_deleted_total', 'Total invite link deletions'),
    'toxicity_deleted': Counter('toxicity_deleted_total', 'Total toxicity deletions'),
    'mutes': Counter('mutes_total', 'Total mutes applied'),
    'unmutes': Counter('unmutes_total', 'Total unmutes executed'),
    'api_fallbacks': Counter('api_fallbacks_total', 'Total toxicity API fallbacks'),
}
PROM_SERVICE = Service()
if metrics_enabled:
    for metric in METRICS.values():
        PROM_SERVICE.register(metric)

# Configuration schema
class BotConfig(BaseModel):
    DISCORD_TOKEN: str
    USE_DB: bool = False
    DB_URL: Optional[str] = None
    SHARD_COUNT: Optional[int] = None
    DEV_GUILDS: List[int] = Field(default_factory=list)
    HTTP_PORT: int = 8080
    INTENTS: List[str] = Field(default=["default", "message_content"]) # Updated default

    @property
    def intents(self) -> discord.Intents:
        configured_intents: Set[str] = {intent_name.lower() for intent_name in self.INTENTS}
        final_intents: discord.Intents

        if "all" in configured_intents:
            logger.info("Using all privileged and unprivileged intents based on 'all' in config.")
            return discord.Intents.all()

        if "default" in configured_intents:
            final_intents = discord.Intents.default()
            logger.info("Starting with default intents.")
        else:
            final_intents = discord.Intents.none()
            logger.info("Starting with no intents. Explicitly enable desired intents in config.")

        # Apply specific intents from config
        # Order doesn't strictly matter here as we're ORing bits
        if "message_content" in configured_intents or "messages" in configured_intents:
            if not final_intents.message_content: # Only enable if not already part of default/all
                logger.info("Enabling message content intent.")
                final_intents.message_content = True
        if "members" in configured_intents:
            if not final_intents.members:
                logger.info("Enabling members intent (privileged).")
                final_intents.members = True
        if "presences" in configured_intents:
            if not final_intents.presences:
                logger.info("Enabling presences intent (privileged).")
                final_intents.presences = True
        if "guilds" in configured_intents: # Part of default, but can be explicit
            if not final_intents.guilds: # Should be covered by default usually
                logger.info("Enabling guilds intent.")
                final_intents.guilds = True
        if "reactions" in configured_intents:
            if not final_intents.reactions:
                logger.info("Enabling reactions intent.")
                final_intents.reactions = True
        # Add more specific intent checks as needed:
        # e.g., bans, emojis, integrations, webhooks, invites, voice_states, typing etc.

        if final_intents == discord.Intents.none() and "none" not in configured_intents:
            logger.warning("No intents were enabled, but 'none' was not explicitly specified. "
                           "The bot might lack necessary permissions. Consider starting with 'default'.")
        
        active_intent_names = [name for name, value in final_intents if value]
        if active_intent_names:
            logger.info(f"Final calculated intents: {', '.join(active_intent_names)}")
        else:
            logger.info("Final calculated intents: None")
            
        return final_intents

CONFIG: BotConfig

# Load and validate config
def load_config() -> BotConfig:
    try:
        raw_config = Path(CONFIG_PATH).read_text()
    except FileNotFoundError:
        logger.critical(f"Config file not found: {CONFIG_PATH}")
        raise SystemExit(1)
    try:
        data = yaml.safe_load(raw_config) or {}
        cfg = BotConfig(**data)
        logger.info("Config loaded and validated successfully.")
        return cfg
    except ValidationError as e:
        logger.critical(f"Configuration validation error:\n{e}")
        raise SystemExit(1)
    except yaml.YAMLError as e:
        logger.critical(f"Error parsing YAML configuration file: {CONFIG_PATH}\n{e}")
        raise SystemExit(1)


# HTTP endpoints
async def health(request):
    return web.Response(text="OK")

async def metrics_http(request): # Renamed to avoid conflict with metrics module/variable
    return await PROM_SERVICE.handle(request)

async def dashboard(request):
    bot = request.app['bot']
    html_content = (
        f"<html><head><title>Bot Dashboard</title></head><body>"
        f"<h1>Bot Analytics & Status</h1>"
        f"<p>Bot User: {bot.user} (ID: {bot.user.id if bot.user else 'N/A'})</p>"
        f"<p>Shard count: {bot.shard_count or 'N/A (possibly not sharded or not fully ready)'}</p>"
        f"<p>Latency: {bot.latency*1000:.2f} ms</p>"
        f"<p>Guilds: {len(bot.guilds)}</p>"
        f"<p>Loaded extensions: {', '.join(bot.extensions.keys()) or 'None'}</p>"
        f"<p>Dev guilds: {', '.join(map(str, bot.config.DEV_GUILDS)) or 'None'}</p>"
        f"<p>Metrics: <a href='/metrics'>/metrics</a></p>"
        f"</body></html>"
    )
    return web.Response(text=html_content, content_type='text/html')

async def start_http_server(bot):
    app = web.Application()
    app['bot'] = bot # Make bot instance available to handlers
    app.router.add_get('/health', health)
    app.router.add_get('/metrics', metrics_http)
    app.router.add_get('/dashboard', dashboard)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', CONFIG.HTTP_PORT) # Listen on all interfaces
    try:
        await site.start()
        bot.http_runner = runner # Store runner for cleanup
        logger.info(f"HTTP server running on http://0.0.0.0:{CONFIG.HTTP_PORT}")
    except OSError as e:
        logger.error(f"Failed to start HTTP server on port {CONFIG.HTTP_PORT}: {e}. "
                     "Port might be in use or insufficient permissions.")
        bot.http_runner = None # Ensure it's None if start fails


class SlashBot(commands.Bot):
    def __init__(self, config: BotConfig) -> None:
        super().__init__(
            command_prefix=[], # Updated: No standard prefix for message commands
            intents=config.intents,
            help_command=None, # Recommended for slash command focused bots
            shard_count=config.SHARD_COUNT
        )
        self.config = config
        self.db: Optional[asyncpg.Pool] = None
        self.watch_task: Optional[asyncio.Task] = None
        self.http_runner: Optional[web.AppRunner] = None

    async def setup_hook(self) -> None:
        # Database initialization
        if self.config.USE_DB and self.config.DB_URL:
            try:
                self.db = await asyncpg.create_pool(self.config.DB_URL, max_inactive_connection_lifetime=60) # Added timeout
                # Test connection
                async with self.db.acquire() as conn:
                    await conn.execute("SELECT 1")
                
                # Ensure tables exist
                await self.db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mutes (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        unmute_time TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (guild_id, user_id)
                    );
                    """
                )
                await self.db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blacklist (
                        guild_id BIGINT NOT NULL,
                        word TEXT NOT NULL,
                        PRIMARY KEY (guild_id, word)
                    );
                    """
                )
                logger.info("PostgreSQL database connected and tables ensured.")
            except Exception as e:
                logger.error(f"PostgreSQL database initialization failed: {e}", exc_info=True)
                self.db = None # Ensure db is None if connection fails
        else:
            logger.info("Database usage is disabled in config; skipping initialization.")

        # Start HTTP server (do this before loading extensions that might need the bot fully up)
        await start_http_server(self)

        # Load extensions
        await self.load_extensions_initial() # Renamed for clarity
        # Start watching folders for changes *after* initial load
        self.watch_task = asyncio.create_task(self.watch_folders())

        # Sync slash commands to dev guilds
        if self.config.DEV_GUILDS:
            logger.info(f"Syncing commands to development guilds: {self.config.DEV_GUILDS}")
            for gid in self.config.DEV_GUILDS:
                guild = Object(id=gid)
                self.tree.copy_global_to(guild=guild) # Copy global commands to dev guild
                try:
                    await self._sync_with_backoff(guild=guild)
                    logger.info(f"Successfully synced commands to dev guild {gid}.")
                except Exception as e:
                    logger.error(f"Failed to sync commands to dev guild {gid}: {e}", exc_info=True)
            logger.info("Development guild command syncing process complete.")
        else:
            logger.info("No development guilds configured for initial command sync.")
            # If you have global commands and no dev guilds, you might want to sync globally here
            # await self._sync_with_backoff() 
            # Be cautious with global syncs; they can take up to an hour to propagate.


    async def _sync_with_backoff(self, *, guild: Optional[discord.Object] = None):
        backoff = 1
        max_backoff = 60
        max_retries = 5
        attempt = 0
        while attempt < max_retries:
            attempt +=1
            try:
                if guild:
                    await self.tree.sync(guild=guild)
                else: # Global sync
                    await self.tree.sync()
                logger.info(f"Command tree synced {'globally' if not guild else f'for guild {guild.id}'}.")
                return
            except discord.HTTPException as e:
                if attempt >= max_retries:
                    logger.error(f"Max retries reached for command sync {'globally' if not guild else f'for guild {guild.id}'}. Last error: {e}", exc_info=True)
                    raise # Re-raise the last exception
                logger.warning(f"Command sync failed (attempt {attempt}/{max_retries}), retrying in {backoff}s. Error: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except Exception as e: # Catch other potential errors during sync
                logger.error(f"An unexpected error occurred during command sync: {e}", exc_info=True)
                raise


    async def load_extensions_initial(self):
        logger.info("Starting initial loading of extensions...")
        for folder in (COGS_DIR, PLUGINS_DIR):
            for file in folder.glob("*.py"):
                if file.stem == "__init__":
                    continue
                ext_name = f"{folder.name}.{file.stem}"
                if ext_name not in self.extensions:
                    try:
                        await self.load_extension(ext_name)
                        logger.info(f"Successfully loaded extension: {ext_name}")
                    except Exception as e:
                        logger.error(f"Failed to load extension {ext_name} during initial load.", exc_info=True)
                else:
                    logger.debug(f"Extension {ext_name} already loaded (skipped initial).")
        logger.info("Initial extension loading process complete.")

    async def watch_folders(self):
        last_mtimes = {}
        # Populate initial mtimes for already existing files
        for folder in (COGS_DIR, PLUGINS_DIR):
            for file in folder.glob("*.py"):
                if file.stem == "__init__": continue
                try:
                    last_mtimes[str(file.resolve())] = file.stat().st_mtime
                except FileNotFoundError: pass # Should not happen here normally

        logger.info(f"Hot-reloader watching folders: {COGS_DIR.name}, {PLUGINS_DIR.name}")
        while True:
            await asyncio.sleep(5) # Polling interval
            changed_extensions_this_cycle = False
            current_files_in_watched_folders = set()

            for folder in (COGS_DIR, PLUGINS_DIR):
                for file in folder.glob("*.py"):
                    if file.stem == "__init__":
                        continue
                    
                    path_str = str(file.resolve())
                    current_files_in_watched_folders.add(path_str)
                    ext_name = f"{folder.name}.{file.stem}"

                    try:
                        current_mtime = file.stat().st_mtime
                    except FileNotFoundError:
                        # This case should ideally be caught by the deletion check later
                        # but if a file vanishes between glob and stat:
                        if path_str in last_mtimes:
                            logger.warning(f"File {path_str} disappeared unexpectedly during mtime check.")
                            # Attempt to unload if it was known
                            if ext_name in self.extensions:
                                try:
                                    await self.unload_extension(ext_name)
                                    logger.info(f"Unloaded {ext_name} due to disappearance.")
                                    changed_extensions_this_cycle = True
                                except Exception as e_unload:
                                    logger.error(f"Error unloading {ext_name}: {e_unload}", exc_info=True)
                            del last_mtimes[path_str]
                        continue

                    if path_str not in last_mtimes: # New file
                        logger.info(f"Detected new file {file.name} in {folder.name}. Attempting to load extension {ext_name}...")
                        try:
                            await self.load_extension(ext_name)
                            logger.info(f"Successfully loaded new extension: {ext_name}")
                            changed_extensions_this_cycle = True
                        except commands.ExtensionAlreadyLoaded:
                             logger.warning(f"Extension {ext_name} reported as already loaded (new file). Attempting reload.")
                             try:
                                await self.reload_extension(ext_name)
                                logger.info(f"Reloaded {ext_name} (new file, was already loaded).")
                                changed_extensions_this_cycle = True
                             except Exception as e_reload:
                                logger.error(f"Error reloading {ext_name}: {e_reload}", exc_info=True)
                        except Exception as e_load:
                            logger.error(f"Failed to load new extension {ext_name}: {e_load}", exc_info=True)
                        last_mtimes[path_str] = current_mtime
                    elif last_mtimes[path_str] != current_mtime: # Existing file changed
                        logger.info(f"Detected change in {file.name} in {folder.name}. Attempting to reload extension {ext_name}...")
                        try:
                            if ext_name not in self.extensions: # Should be loaded if mtime was tracked
                                logger.warning(f"Extension {ext_name} was not loaded but file changed. Attempting to load.")
                                await self.load_extension(ext_name)
                                logger.info(f"Loaded changed extension: {ext_name}")
                            else:
                                await self.reload_extension(ext_name)
                                logger.info(f"Successfully reloaded extension: {ext_name}")
                            changed_extensions_this_cycle = True
                        except Exception as e_reload:
                            logger.error(f"Failed to reload extension {ext_name}: {e_reload}", exc_info=True)
                        last_mtimes[path_str] = current_mtime
            
            # Check for deleted files
            deleted_paths = set(last_mtimes.keys()) - current_files_in_watched_folders
            for path_str in deleted_paths:
                # Determine folder and stem from path_str for ext_name
                p = Path(path_str)
                folder_name = p.parent.name # e.g. "cogs" or "plugins"
                file_stem = p.stem
                ext_name = f"{folder_name}.{file_stem}"
                logger.info(f"Detected deletion of {p.name} in {folder_name}. Attempting to unload extension {ext_name}...")
                if ext_name in self.extensions:
                    try:
                        await self.unload_extension(ext_name)
                        logger.info(f"Successfully unloaded extension: {ext_name}")
                        changed_extensions_this_cycle = True
                    except Exception as e_unload:
                        logger.error(f"Failed to unload extension {ext_name}: {e_unload}", exc_info=True)
                del last_mtimes[path_str]

            if changed_extensions_this_cycle and self.config.DEV_GUILDS:
                logger.info("Extension changes detected, re-syncing commands to development guilds...")
                for gid in self.config.DEV_GUILDS:
                    guild = Object(id=gid)
                    self.tree.copy_global_to(guild=guild)
                    try:
                        await self._sync_with_backoff(guild=guild)
                    except Exception as e_sync: # Catch sync specific errors here
                         logger.error(f"Failed to re-sync commands to dev guild {gid} after hot-reload: {e_sync}", exc_info=True)
                logger.info("Development guild command re-sync after hot-reload complete.")
            elif changed_extensions_this_cycle:
                 logger.info("Extension changes detected. No DEV_GUILDS configured for automatic re-sync.")


    async def close(self):
        logger.info("Shutting down bot...")
        # Cancel watch task
        if self.watch_task:
            self.watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watch_task
                logger.info("File watcher task cancelled.")
        
        # Cleanup HTTP server
        if self.http_runner:
            await self.http_runner.cleanup()
            logger.info("HTTP server cleaned up.")
        
        # Close database pool
        if self.db:
            await self.db.close()
            logger.info("Database pool closed.")
            
        await super().close()
        logger.info("Bot has been closed.")

    async def on_ready(self):
        logger.info(f"Bot connected as {self.user} (ID: {self.user.id})")
        logger.info(f"Operating in {len(self.guilds)} guild(s).")
        # Example: Sync global commands if not using dev guilds or after dev setup
        # if not self.config.DEV_GUILDS:
        #    logger.info("No dev guilds specified, attempting global command sync.")
        #    await self._sync_with_backoff()


    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Log the full error for debugging
        logger.error(f"Slash command error in '{interaction.command.name if interaction.command else 'unknown command'}': {error}", exc_info=True)

        # User-facing messages
        user_message = "An unexpected error occurred while processing your command."
        if isinstance(error, app_commands.CommandNotFound):
            user_message = "Sorry, I couldn't find that command." # Should be rare with synced commands
        elif isinstance(error, app_commands.MissingPermissions):
            user_message = f"You lack the required permissions: {', '.join(error.missing_permissions)}"
        elif isinstance(error, app_commands.BotMissingPermissions):
            user_message = f"I lack the required permissions to do that: {', '.join(error.missing_permissions)}"
        elif isinstance(error, app_commands.CommandOnCooldown):
            user_message = f"This command is on cooldown. Try again in {error.retry_after:.2f} seconds."
        elif isinstance(error, app_commands.CheckFailure): # Generic check failure
            user_message = "You do not meet the requirements to use this command."
        # Add more specific error handling as needed

        try:
            if interaction.response.is_done():
                await interaction.followup.send(user_message, ephemeral=True)
            else:
                await interaction.response.send_message(user_message, ephemeral=True)
        except discord.HTTPException as e:
            logger.error(f"Failed to send error message to interaction: {e}")

    # Example built-in slash command (can be moved to a cog)
    @app_commands.command(name="greet", description="Sends a friendly greeting.")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id)) # Example cooldown
    async def greet(self, interaction: discord.Interaction, name: Optional[str] = None):
        """Greets the user or a specified name."""
        target_name = name or interaction.user.mention
        await interaction.response.send_message(f"Hello {target_name}!")
        METRICS['blacklist_hits'].inc() # Example metric increment

    @app_commands.command(name="reload_cog", description="Reloads a specific cog (Bot Owner Only).")
    @app_commands.describe(cog_name="The name of the cog to reload (e.g., 'admin' for cogs.admin).")
    async def reload_cog_command(self, interaction: discord.Interaction, cog_name: str):
        """Reloads a cog from the 'cogs' directory."""
        if not await self.is_owner(interaction.user):
            return await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)

        # We assume cogs are in COGS_DIR for this specific command.
        # If plugins can also be reloaded this way, the command might need a folder_type parameter.
        target_extension = f"{COGS_DIR.name}.{cog_name.lower().replace('.py', '')}"
        
        try:
            if target_extension not in self.extensions:
                 await interaction.response.send_message(f"Cog '{target_extension}' is not currently loaded. Attempting to load...", ephemeral=True)
                 await self.load_extension(target_extension)
                 message = f"Successfully loaded cog: {target_extension}"
            else:
                await self.reload_extension(target_extension)
                message = f"Successfully reloaded cog: {target_extension}"
            
            # Re-sync commands for the current guild if this is a dev guild, or globally if appropriate
            if interaction.guild and interaction.guild_id in self.config.DEV_GUILDS:
                self.tree.copy_global_to(guild=interaction.guild) # Ensure global commands are copied
                await self._sync_with_backoff(guild=interaction.guild)
                message += " Commands re-synced for this dev guild."
            
            await interaction.followup.send(message, ephemeral=True) if interaction.response.is_done() else await interaction.response.send_message(message, ephemeral=True)
            logger.info(f"Cog '{target_extension}' processed via command by {interaction.user}.")

        except commands.ExtensionNotFound:
            await interaction.response.send_message(f"Cog '{target_extension}' not found.", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to reload/load cog {target_extension}: {e}", exc_info=True)
            err_msg = f"An error occurred while processing cog '{target_extension}': {type(e).__name__} - {e}"
            await interaction.followup.send(err_msg, ephemeral=True) if interaction.response.is_done() else await interaction.response.send_message(err_msg, ephemeral=True)


async def main():
    global CONFIG # CONFIG is loaded here and used by SlashBot instance and HTTP server
    CONFIG = load_config()
    
    bot = SlashBot(CONFIG)

    try:
        await bot.start(CONFIG.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt.")
    except discord.LoginFailure:
        logger.critical("Failed to log in: Invalid Discord token provided.")
    except discord.PrivilegedIntentsRequired:
        logger.critical(
            "Privileged intents (e.g., Server Members, Presence) are required but not enabled in the Discord Developer Portal "
            "for this bot. Please enable them if your bot's functionality depends on them."
        )
    except Exception as e:
        logger.critical(f"An unexpected error occurred during bot startup or runtime: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            logger.info("Ensuring bot is closed...")
            await bot.close()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt: # Catch KI here too if asyncio.run itself is interrupted early
        logger.info("Application shutting down...")