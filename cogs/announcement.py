import discord
from discord import app_commands
from discord.ext import commands

class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_channel = {}  # Dictionary to store last used channel per guild

    @app_commands.command(name="announce", description="Send an announcement to a specific channel.")
    @app_commands.describe(
        channel="The channel to post the announcement in",
        title="Optional custom title (default: 📢 Announcement)",
        message="The announcement message",
        image_url="Optional image URL"
    )
    @app_commands.default_permissions(administrator=True)
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        title: str = "📢 Announcement",
        message: str = None,
        image_url: str = None
    ):
        """
        Slash command to send an announcement.
        
        Usage:
        - `/announce channel:#news title:"Big Update" message:"Something cool!"`
        - `/announce channel:#updates message:"Server maintenance at 9 PM!"`
        - `/announce title:"Reminder" message:"Don't forget to check updates!"` (Uses last used channel)
        - `/announce channel:#general message:"Check this out!" image_url:"https://example.com/image.png"`
        """

        # Use last used channel if no channel is provided
        if not channel:
            if interaction.guild.id in self.last_channel:
                channel = self.last_channel[interaction.guild.id]
            else:
                await interaction.response.send_message("⚠️ **Please select a channel to send the announcement.**", ephemeral=True)
                return

        # Ensure message is provided
        if not message:
            await interaction.response.send_message("⚠️ **You need to provide the announcement message.**", ephemeral=True)
            return

        # Check bot permissions
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message(f"🚫 **I don't have permission to send messages in {channel.mention}.**", ephemeral=True)
            return
        if not channel.permissions_for(interaction.guild.me).embed_links:
            await interaction.response.send_message(f"🚫 **I don't have permission to send embeds in {channel.mention}.**", ephemeral=True)
            return

        # Save the last used channel
        self.last_channel[interaction.guild.id] = channel

        # Check for @everyone or @here mentions
        mention_everyone = "@everyone" in message or "@here" in message

        # Create embed
        embed = discord.Embed(
            title=title,
            description=message,
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Announced by {interaction.user.display_name}")
        
        # Handle image attachment or URL
        if image_url:
            if image_url.startswith("http") and (image_url.endswith(".png") or image_url.endswith(".jpg") or image_url.endswith(".jpeg")):
                embed.set_image(url=image_url)
            else:
                await interaction.response.send_message("⚠️ **Invalid image URL! Must end in .png, .jpg, or .jpeg.**", ephemeral=True)
                return
        elif interaction.message and interaction.message.attachments:
            embed.set_image(url=interaction.message.attachments[0].url)

        # Send the announcement
        try:
            if mention_everyone:
                await channel.send(content="@everyone" if "@everyone" in message else "@here", embed=embed)
            else:
                await channel.send(embed=embed)

            await interaction.response.send_message(f"✅ **Announcement successfully sent in {channel.mention}!**", ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message("🚨 **I don't have permission to send messages in that channel.**", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("⚠️ **An error occurred while sending the announcement. Please try again.**", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Announcement(bot))
