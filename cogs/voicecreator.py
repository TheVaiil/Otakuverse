import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
from typing import Literal, Optional

class VoiceConfig:
    def __init__(self, guild_id):
        self.guild_id = guild_id
        self.templates = {
            'default': {'bitrate': 64000, 'user_limit': 0},
            'meeting': {'bitrate': 96000, 'user_limit': 5},
            'gaming': {'bitrate': 128000, 'user_limit': 10}
        }
        self.category_id = None
        self.allow_custom = True

    def to_dict(self):
        return self.__dict__

class TempVoiceSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.configs = self._load_configs()
        self.persistent = True  # Set to False for memory-only storage

    def _load_configs(self):
        try:
            with open('voice_configs.json') as f:
                data = json.load(f)
                return {int(k): VoiceConfig(**v) for k, v in data.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_configs(self):
        if not self.persistent:
            return
        data = {k: v.to_dict() for k, v in self.configs.items()}
        with open('voice_configs.json', 'w') as f:
            json.dump(data, f)

    async def _get_category(self, guild):
        config = self.configs.get(guild.id, VoiceConfig(guild.id))
        if config.category_id:
            category = guild.get_channel(config.category_id)
            if category:
                return category
        category = await guild.create_category("Dynamic Channels")
        config.category_id = category.id
        self.configs[guild.id] = config
        self._save_configs()
        return category

    @app_commands.command(name="voice", description="Manage temporary voice channels")
    @app_commands.describe(
        action="Channel action",
        name="Custom channel name",
        limit="User limit (0 = unlimited)",
        template="Channel template preset",
        privacy="Channel visibility"
    )
    async def voice_command(
        self,
        interaction: discord.Interaction,
        action: Literal["create", "configure", "delete"],
        name: Optional[str] = None,
        limit: Optional[app_commands.Range[int, 0, 99]] = 0,
        template: Optional[Literal["default", "meeting", "gaming"]] = "default",
        privacy: Literal["public", "private"] = "public"
    ):
        """Main voice channel management command"""
        await interaction.response.defer(ephemeral=True)
        
        if action == "create":
            await self._create_voice(interaction, name, limit, template, privacy)
        elif action == "configure":
            await self._configure_voice(interaction, name, limit, privacy)
        elif action == "delete":
            await self._delete_voice(interaction)

    async def _create_voice(self, interaction, name, limit, template, privacy):
        # Check existing channels
        if interaction.user.id in self.sessions:
            await interaction.followup.send("❌ You already have an active channel!", ephemeral=True)
            return

        # Get template settings
        config = self.configs.get(interaction.guild.id, VoiceConfig(interaction.guild.id))
        template_settings = config.templates.get(template, config.templates['default'])
        
        # Create voice channel
        try:
            category = await self._get_category(interaction.guild)
            channel = await interaction.guild.create_voice_channel(
                name=name or f"{interaction.user.display_name}'s Channel",
                user_limit=limit or template_settings['user_limit'],
                bitrate=template_settings['bitrate'],
                category=category,
                reason=f"Temp channel created by {interaction.user}"
            )

            # Create linked text channel
            text_channel = await interaction.guild.create_text_channel(
                name=f"chat-{channel.name}",
                category=category,
                overwrites={
                    interaction.guild.default_role: discord.PermissionOverwrite(
                        view_channel=privacy == "public"
                    )
                }
            )

            # Store session data
            self.sessions[interaction.user.id] = {
                "voice": channel.id,
                "text": text_channel.id,
                "owner": interaction.user.id,
                "privacy": privacy
            }

            await interaction.followup.send(
                f"✅ Created {channel.mention} with {text_channel.mention}!\n"
                f"Use `/voice configure` to manage settings.",
                ephemeral=True
            )

        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed to create channel: {e}", ephemeral=True)

    async def _configure_voice(self, interaction, name, limit, privacy):
        session = self.sessions.get(interaction.user.id)
        if not session:
            await interaction.followup.send("❌ You don't own any active channels!", ephemeral=True)
            return

        channel = interaction.guild.get_channel(session['voice'])
        if not channel:
            await interaction.followup.send("❌ Channel not found!", ephemeral=True)
            return

        updates = {}
        if name and name != channel.name:
            updates['name'] = name
        if limit and limit != channel.user_limit:
            updates['user_limit'] = limit
        if privacy != session['privacy']:
            text_channel = interaction.guild.get_channel(session['text'])
            if text_channel:
                await text_channel.set_permissions(
                    interaction.guild.default_role,
                    view_channel=privacy == "public"
                )
            updates['privacy'] = privacy

        try:
            if updates:
                await channel.edit(**updates)
                self.sessions[interaction.user.id].update(updates)
                await interaction.followup.send("✅ Channel updated successfully!", ephemeral=True)
            else:
                await interaction.followup.send("ℹ️ No changes detected.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed to update channel: {e}", ephemeral=True)

    async def _delete_voice(self, interaction):
        session = self.sessions.pop(interaction.user.id, None)
        if not session:
            await interaction.followup.send("❌ No active channel found!", ephemeral=True)
            return

        try:
            channel = interaction.guild.get_channel(session['voice'])
            text_channel = interaction.guild.get_channel(session['text'])
            if channel:
                await channel.delete(reason="User requested deletion")
            if text_channel:
                await text_channel.delete(reason="User requested deletion")
            await interaction.followup.send("✅ Channel deleted successfully!", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("❌ Failed to delete channel!", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Automatic cleanup system
        if before.channel:
            session = next((s for s in self.sessions.values() if s['voice'] == before.channel.id), None)
            if session and len(before.channel.members) == 0:
                await asyncio.sleep(300)  # 5-minute grace period
                if before.channel and len(before.channel.members) == 0:
                    await self._cleanup_channel(before.channel, session)

    async def _cleanup_channel(self, channel, session):
        try:
            text_channel = channel.guild.get_channel(session['text'])
            if text_channel:
                await text_channel.delete()
            await channel.delete()
            self.sessions.pop(session['owner'], None)
        except discord.HTTPException:
            pass

    @app_commands.command(name="voice-admin", description="Configure voice system settings")
    @app_commands.default_permissions(manage_guild=True)
    async def voice_admin(
        self,
        interaction: discord.Interaction,
        action: Literal["add-template", "remove-template", "set-category"],
        template_name: Optional[str] = None,
        bitrate: Optional[app_commands.Range[int, 8000, 384000]] = None,
        user_limit: Optional[app_commands.Range[int, 0, 99]] = None
    ):
        """Administrative configuration command"""
        await interaction.response.defer(ephemeral=True)
        config = self.configs.setdefault(interaction.guild.id, VoiceConfig(interaction.guild.id))

        if action == "add-template":
            if not template_name or not bitrate:
                await interaction.followup.send("❌ Missing required parameters!", ephemeral=True)
                return

            config.templates[template_name] = {
                'bitrate': bitrate,
                'user_limit': user_limit or 0
            }
            self._save_configs()
            await interaction.followup.send(f"✅ Added template '{template_name}'!", ephemeral=True)

        elif action == "remove-template":
            if template_name in config.templates:
                del config.templates[template_name]
                self._save_configs()
                await interaction.followup.send(f"✅ Removed template '{template_name}'!", ephemeral=True)
            else:
                await interaction.followup.send("❌ Template not found!", ephemeral=True)

        elif action == "set-category":
            category = await self._get_category(interaction.guild)
            await interaction.followup.send(f"✅ Channel category set to {category.mention}!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TempVoiceSystem(bot))