import discord
from discord.ext import commands, tasks
from discord import app_commands
from mcstatus import JavaServer
import logging

# Import the older RCON connection class
try:
    from mcstatus.rcon import RCONConnection
except ImportError:
    RCONConnection = None  # If this is None, it means the mcstatus version is too old

logger = logging.getLogger("minecraft_status")

class MinecraftStatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # -----------------------
        #    CONFIGURATION
        # -----------------------
        self.server_ip = "51.77.35.232"
        self.server_port = 25565
        self.server_name = "Flintsten SMP"

        self.embed_icon = "https://static.wikia.nocookie.net/minecraft_gamepedia/images/0/0d/Grass_Block_JE6_BE5.png"

        # Offline/online alert channel
        self.alert_channel_id = None  # e.g., 123456789012345678

        # RCON details
        # We will use RCONConnection if it's available
        self.rcon_enabled = True
        self.rcon_password = "myRconPassword"
        self.rcon_port = 25576

        self.previous_status_online = None
        self.last_known_tps = None

    # -------------------------------------------
    # Helper function for older mcstatus RCON
    # -------------------------------------------
    def rcon_command(self, host: str, port: int, password: str, command: str) -> str:
        """
        Executes a command on the server via RCONConnection (older mcstatus style).
        Returns the command output as a string, or raises an Exception if fails.
        """
        if not RCONConnection:
            # If mcstatus.rcon doesn't exist, user must upgrade or use a separate library
            raise RuntimeError("RCONConnection is unavailable in this mcstatus version.")

        logger.info("Using RCONConnection on %s:%s to run command: %s", host, port, command)
        conn = RCONConnection(host, port, password)
        conn.connect()
        result = conn.command(command)
        conn.disconnect()
        return result

    # -------------------------------------------
    #  Slash Command: /mcstatus
    # -------------------------------------------
    @app_commands.command(name="mcstatus", description="Check Minecraft server status.")
    async def mcstatus(self, interaction: discord.Interaction):
        await interaction.response.defer()

        logger.info("User %s requested /mcstatus", interaction.user)
        server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")

        try:
            status = await server.async_status()  # .async_status() works even in older mcstatus 11.x
            latency = round(status.latency, 2)

            # Attempt to parse MOTD
            motd_str = ""
            if hasattr(status, "description"):
                if isinstance(status.description, str):
                    motd_str = status.description
                elif isinstance(status.description, dict):
                    motd_str = status.description.get("text", "No MOTD")
            else:
                motd_str = "No MOTD"

            embed = discord.Embed(
                title=f"✅ {self.server_name} is Online!",
                color=discord.Color.green(),
                description=f"**MOTD:** {motd_str}"
            )
            embed.set_thumbnail(url=self.embed_icon)
            embed.add_field(name="Server IP", value=f"{self.server_ip}:{self.server_port}", inline=False)
            embed.add_field(name="Players", value=f"{status.players.online}/{status.players.max}", inline=True)
            embed.add_field(name="Version", value=status.version.name, inline=True)
            embed.add_field(name="Latency", value=f"{latency} ms", inline=True)

            # Show online players + heads if available
            if status.players.sample:
                lines = []
                for player in status.players.sample:
                    head_url = f"https://minotar.net/avatar/{player.name}/32"
                    lines.append(f"[{player.name}]({head_url})")
                players_str = "\n".join(lines)
                embed.add_field(name="Online Players", value=players_str, inline=False)

            logger.info("Server is online with %s players online.", status.players.online)

        except Exception as e:
            logger.error("Error fetching server status: %s", e, exc_info=True)
            embed = discord.Embed(
                title=f"❌ {self.server_name} is Offline!",
                description="Server seems unreachable or offline. Try again later.",
                color=discord.Color.red(),
            )
            embed.set_thumbnail(url=self.embed_icon)
            embed.set_footer(text="Minecraft Server Status")
            await interaction.followup.send(embed=embed)
            return

        await interaction.followup.send(embed=embed)

    # -------------------------------------------
    #  Slash Command: /mctps
    # -------------------------------------------
    @app_commands.command(name="mctps", description="Show last known TPS (requires RCON).")
    async def mctps(self, interaction: discord.Interaction):
        logger.info("User %s requested /mctps", interaction.user)

        if not self.rcon_enabled:
            await interaction.response.send_message(
                "RCON features are disabled in this cog configuration.",
                ephemeral=True
            )
            return

        if not self.last_known_tps or self.last_known_tps == "Error fetching TPS":
            await interaction.response.send_message(
                f"Current TPS from last RCON query: `{self.last_known_tps}`\n"
                "Either the server is offline or TPS couldn't be fetched yet.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{self.server_name} TPS",
            description=f"Current TPS from last RCON query: `{self.last_known_tps}`",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=self.embed_icon)
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------
    #  Slash Command: /mcrcon
    # -------------------------------------------
    @app_commands.command(name="mcrcon", description="Send a command to the server via RCON (owner only).")
    async def mcrcon(self, interaction: discord.Interaction, *, command_str: str):
        logger.info("User %s requested /mcrcon with command '%s'", interaction.user, command_str)

        if not self.rcon_enabled:
            await interaction.response.send_message(
                "RCON features are disabled in this cog configuration.",
                ephemeral=True
            )
            return

        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Only the bot owner can use this.", ephemeral=True)
            return

        if not RCONConnection:
            await interaction.response.send_message(
                "Your mcstatus version is too old to support RCON. Please update or install a separate RCON library.",
                ephemeral=True
            )
            return

        try:
            result = self.rcon_command(self.server_ip, self.rcon_port, self.rcon_password, command_str)
            if not result:
                result = "*No output.*"

            embed = discord.Embed(
                title=f"RCON Command: {command_str}",
                description=f"```\n{result}\n```",
                color=discord.Color.dark_purple()
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error("RCON command error: %s", e, exc_info=True)
            await interaction.response.send_message(f"Error running RCON command:\n```{e}```", ephemeral=True)

    # -------------------------------------------
    #  BACKGROUND TASK: Check server status & TPS
    # -------------------------------------------
    @tasks.loop(seconds=60)
    async def monitor_server(self):
        """Checks if the server is online/offline, updates TPS (if RCON is enabled)."""
        logger.info("Starting server check for %s:%s", self.server_ip, self.server_port)
        is_online = False

        try:
            server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")
            await server.async_status()  # still asynchronous for normal status
            is_online = True
        except Exception as e:
            logger.warning("Server is offline or unreachable: %s", e)

        logger.info("Server is online? %s", is_online)

        # 1) If RCON is enabled and server is online, try getting TPS
        if is_online and self.rcon_enabled and RCONConnection:
            try:
                tps_output = self.rcon_command(self.server_ip, self.rcon_port, self.rcon_password, "tps")
                if tps_output:
                    self.last_known_tps = tps_output.strip()
                    logger.info("TPS output: %s", self.last_known_tps)
                else:
                    self.last_known_tps = "No TPS output."
            except Exception as e:
                logger.error("RCON TPS fetch error: %s", e, exc_info=True)
                self.last_known_tps = "Error fetching TPS"
        else:
            self.last_known_tps = None

        # 2) Check if status changed (online <-> offline)
        if self.previous_status_online is None:
            self.previous_status_online = is_online
            return

        if is_online != self.previous_status_online:
            self.previous_status_online = is_online
            logger.info("Server status changed to %s", "online" if is_online else "offline")

            if self.alert_channel_id is not None:
                channel = self.bot.get_channel(self.alert_channel_id)
                if channel:
                    status_str = "online" if is_online else "offline"
                    await channel.send(f"**{self.server_name}** is now **{status_str}**!")

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.monitor_server.is_running():
            logger.info("Starting monitor_server background task.")
            self.monitor_server.start()
        print(f"{self.__class__.__name__} loaded successfully!")

async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftStatusCog(bot))
