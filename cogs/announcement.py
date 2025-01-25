import discord
from discord.ext import commands

class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="announce", aliases=["ann"])
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, *, content=None):
        """Create an announcement in the announcements channel with a rich embed."""
        if not content:
            await ctx.send("Please provide the announcement content.")
            return

        embed = discord.Embed(
            title="📢 Announcement",
            description=content,
            color=discord.Color.gold()
        )
        embed.set_footer(text="Regards, Otakuverse")
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)

        # Send the embed to the announcements channel
        announcements_channel = discord.utils.get(ctx.guild.channels, name="announcements")
        if announcements_channel:
            await announcements_channel.send(embed=embed)
            await ctx.send("Announcement posted successfully!")
        else:
            await ctx.send("Could not find an announcements channel. Please create one.")

async def setup(bot):
    await bot.add_cog(Announcement(bot))
