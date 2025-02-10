import discord
from discord.ext import commands
import asyncio
import json
import openai
import yaml
import re
import time
import logging
from collections import defaultdict, deque

def load_config():
    """
    Loads your config for the OpenAI API key and any other settings.
    """
    with open("config/config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# ============================== FILE-BASED STORAGE ==============================
class JsonDatabase:
    """
    Manages JSON file interactions for warnings, mutes, and blacklisted words.
    """
    def __init__(self, filename="data.json"):
        self.filename = filename
        self.data = self.load_data()

    def load_data(self):
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"warnings": {}, "mutes": {}, "blacklist": []}

    def save_data(self):
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def get_warnings(self, user_id):
        return self.data["warnings"].get(str(user_id), 0)

    def increment_warning(self, user_id):
        user_id = str(user_id)
        self.data["warnings"][user_id] = self.get_warnings(user_id) + 1
        self.save_data()

    def clear_warnings(self, user_id):
        user_id = str(user_id)
        self.data["warnings"].pop(user_id, None)
        self.save_data()

    def get_blacklist(self):
        return self.data.get("blacklist", [])
    
    def add_blacklist_word(self, word):
        if word.lower() not in self.data["blacklist"]:
            self.data["blacklist"].append(word.lower())
            self.save_data()
    
    def remove_blacklist_word(self, word):
        if word.lower() in self.data["blacklist"]:
            self.data["blacklist"].remove(word.lower())
            self.save_data()

# ============================== BLACKLIST CHECK ==============================
class BlacklistCheck:
    """
    A check that detects blacklisted words using a compiled regex.
    """
    def __init__(self, db: JsonDatabase):
        self.db = db
        self.regex = re.compile(r"(?!x)x", re.IGNORECASE)  # Empty regex initially
        self.logger = logging.getLogger("BlacklistCheck")
    
    def update_blacklist(self):
        words = self.db.get_blacklist()
        pattern = "|".join(re.escape(w) for w in words) or r"(?!x)x"
        self.regex = re.compile(pattern, re.IGNORECASE)
    
    def run(self, content: str):
        return bool(self.regex.search(content))

# ============================== TOXICITY CHECK ==============================
class ToxicityCheck:
    def __init__(self, openai_api_key: str, model="gpt-3.5-turbo"):
        import openai
        openai.api_key = openai_api_key
        self.model = model
        self.logger = logging.getLogger("ToxicityCheck")
    
    def preprocess_text(self, text: str):
        """Prevents AI evasion by normalizing message content."""
        text = re.sub(r'[^\w\s]', '', text)  # Remove special characters
        text = re.sub(r'\s+', ' ', text).strip()  # Normalize spaces
        return text
    
    async def run(self, message: discord.Message):
        try:
            content = self.preprocess_text(message.content)
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a toxicity detection system. Respond ONLY with 'YES' if the message is toxic, or 'NO' if it is not toxic."},
                    {"role": "user", "content": f"Is the following message toxic? '{content}'"}
                ],
                max_tokens=5,
                temperature=0.0
            )
            reply = response['choices'][0]['message']['content'].strip().lower()
            return reply.startswith("yes")
        except Exception as e:
            self.logger.error(f"Toxicity detection error: {e}")
            return False

# ============================== THE ACTUAL COG ==============================
class AIAutoMod(commands.Cog):
    """
    Main Cog that wires up the single on_message event.
    Also includes admin commands for blacklists, warnings, etc.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("AIAutoMod")
        config = load_config()
        self.db = JsonDatabase("data.json")  # JSON file-based storage
        self.blacklist_check = BlacklistCheck(self.db)
        self.toxicity_check = ToxicityCheck(config["OPENAI_API_KEY"], model="gpt-3.5-turbo")
        self.blacklist_check.update_blacklist()
    
    @commands.command(name="add_blacklist")
    @commands.has_permissions(administrator=True)
    async def add_blacklist_command(self, ctx: commands.Context, *, word: str):
        self.db.add_blacklist_word(word.lower())
        self.blacklist_check.update_blacklist()
        await ctx.send(f"Added `{word}` to the blacklist.")
    
    @commands.command(name="remove_blacklist")
    @commands.has_permissions(administrator=True)
    async def remove_blacklist_command(self, ctx: commands.Context, *, word: str):
        self.db.remove_blacklist_word(word.lower())
        self.blacklist_check.update_blacklist()
        await ctx.send(f"Removed `{word}` from the blacklist.")
    
async def setup(bot: commands.Bot):
    """Standard setup for dynamic loading."""
    await bot.add_cog(AIAutoMod(bot))
