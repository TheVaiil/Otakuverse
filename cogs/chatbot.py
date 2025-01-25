import discord
from discord.ext import commands
from yt_dlp import YoutubeDL
import openai

# Initialize OpenAI API key (replace 'YOUR_API_KEY' with your actual key)
openai.api_key = "KEY"

class ChatbotCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ask")
    async def ask(self, ctx, *, question: str):
        """Ask the bot a question and get an AI-powered response."""
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant.."},
                    {"role": "user", "content": question}
                ]
            )
            reply = response['choices'][0]['message']['content']
            embed = discord.Embed(
                title="AI Response",
                description=reply,
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("Sorry, I couldn't process your question right now.")
            print(f"Error with OpenAI API: {e}")

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Example: Detect toxicity (replace with an actual model or API call if needed)
        if "badword" in message.content.lower():
            await message.delete()
            await message.channel.send(f"{message.author.mention}, watch your language!", delete_after=5)

class ImageGeneratorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="generate")
    async def generate_image(self, ctx, *, prompt: str):
        """Generate an image based on a text prompt."""
        try:
            response = openai.Image.create(
                prompt=prompt,
                n=1,
                size="512x512"
            )
            image_url = response['data'][0]['url']
            embed = discord.Embed(title="Generated Image", color=discord.Color.blue())
            embed.set_image(url=image_url)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("Sorry, I couldn't generate the image right now.")
            print(f"Error with OpenAI Image API: {e}")

async def setup(bot):
    await bot.add_cog(ChatbotCog(bot))
    await bot.add_cog(ModerationCog(bot))
    await bot.add_cog(ImageGeneratorCog(bot))
