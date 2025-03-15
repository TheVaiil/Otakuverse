
import discord
from discord import app_commands
from discord.ext import commands, tasks
from mcstatus import JavaServer

class MinecraftStatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # -----------------------
        #    CONFIGURATION
        # -----------------------
        # 1) Server Connection Info
        self.server_ip = "IP"
        self.server_port = 25565
        self.server_name = "Flintsten SMP"

        # 2) Icon for Embeds (Minecraft-related image)
        self.embed_icon = "https://static.wikia.nocookie.net/minecraft_gamepedia/images/0/0d/Grass_Block_JE6_BE5.png"

        # 3) Automatic Offline/Online Alert
        #    Set this to a valid channel ID to receive alerts, or None to disable.
        self.alert_channel_id = ID  # Example: 123456789012345678

        # 4) RCON Configuration (optional)
        #    If None, RCON features (including TPS commands) will be disabled.
        self.rcon_enabled = True
        self.rcon_password = "recon"  # The password from your server.properties
        self.rcon_port = 25575  # Default RCON port if different from your server port

        # Stores last known status to detect status changes
        self.previous_status_online = True
        # Stores last known TPS data from RCON
        self.last_known_tps = True

    # -------------------------------------------
    #  Slash Command: /mcstatus
    # -------------------------------------------
    @app_commands.command(name="mcstatus", description="Check Minecraft server status.")
    async def mcstatus(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Create the JavaServer object
        server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")

        try:
            status = await server.async_status()
            latency = round(status.latency, 2)

            # Attempt to show MOTD if available
            # mcstatus 12+ exposes it as status.description (which can be text or dict)
            motd_str = ""
            if hasattr(status, "description"):
                if isinstance(status.description, str):
                    motd_str = status.description
                elif isinstance(status.description, dict):
                    # Some servers might return a dict with 'text' or 'extra'
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
                player_names = status.players.sample
                # Build a list of "[name](link_to_head)"
                lines = []
                for player in player_names:
                    head_url = f"https://minotar.net/avatar/{player.name}/32"
                    # We'll make the player's name clickable to see their head image
                    lines.append(f"[{player.name}]({head_url})")
                # Join them with newlines
                players_str = "\n".join(lines)
                embed.add_field(name="Online Players", value=players_str, inline=False)

        except Exception:
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
    #  Shows the last known TPS from RCON
    # -------------------------------------------
    @app_commands.command(name="mctps", description="Show last known TPS (requires RCON).")
    async def mctps(self, interaction: discord.Interaction):
        if not self.rcon_enabled:
            await interaction.response.send_message(
                "RCON features are disabled in this cog configuration.",
                ephemeral=True
            )
            return

        if self.last_known_tps is None:
            await interaction.response.send_message(
                "No TPS data available yet. Wait for the background task to update.",
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
    #  Send a command to the server
    #  Only bot owner can use this
    # -------------------------------------------
    @app_commands.command(name="mcrcon", description="Send a command to the server via RCON (owner only).")
    async def mcrcon(self, interaction: discord.Interaction, *, command_str: str):
        if not self.rcon_enabled:
            await interaction.response.send_message(
                "RCON features are disabled in this cog configuration.",
                ephemeral=True
            )
            return

        # Check if user is the bot owner
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Only the bot owner can use this.", ephemeral=True)
            return

        # Attempt to run the command via RCON
        try:
            server = JavaServer.lookup(f"{self.server_ip}:{self.rcon_port}")
            async with server.async_rcon(self.rcon_password) as rcon:
                result = await rcon.run(command_str)
            if not result:
                result = "*No output.*"
            embed = discord.Embed(
                title=f"RCON Command: {command_str}",
                description=f"```\n{result}\n```",
                color=discord.Color.dark_purple()
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"Error running RCON command:\n```{e}```", ephemeral=True)

    # -------------------------------------------
    #  BACKGROUND TASK: Check server status & TPS
    # -------------------------------------------
    @tasks.loop(seconds=60)
    async def monitor_server(self):
        """
        Periodically checks if the server is online/offline, updates TPS (if RCON is enabled),
        and sends an alert if the status changed.
        """
        is_online = False
        try:
            server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")
            await server.async_status()
            is_online = True
        except Exception:
            pass

        # 1) If RCON is enabled and server is online, try getting TPS
        if is_online and self.rcon_enabled:
            try:
                server_for_rcon = JavaServer.lookup(f"{self.server_ip}:{self.rcon_port}")
                async with server_for_rcon.async_rcon(self.rcon_password) as rcon:
                    tps_output = await rcon.run("tps")  # Works on Paper/Spigot
                # Example output: "TPS from last 1m, 5m, 15m: 20.0, 19.9, 20.0"
                self.last_known_tps = tps_output.strip()
            except Exception:
                self.last_known_tps = "Error fetching TPS"

        # 2) Check if status changed (online <-> offline)
        if self.previous_status_online is None:
            # First run, just set the state
            self.previous_status_online = is_online
            return

        if is_online != self.previous_status_online:
            # Status changed
            self.previous_status_online = is_online
            if self.alert_channel_id is not None:
                channel = self.bot.get_channel(self.alert_channel_id)
                if channel:
                    status_str = "online" if is_online else "offline"
                    await channel.send(f"**{self.server_name}** is now **{status_str}**!")

    @commands.Cog.listener()
    async def on_ready(self):
        """
        When the cog is ready, start the background task
        (if it's not already running).
        """
        if not self.monitor_server.is_running():
            self.monitor_server.start()
        print(f"{self.__class__.__name__} loaded successfully!")

async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftStatusCog(bot))
