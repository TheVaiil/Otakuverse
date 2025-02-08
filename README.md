

A robust, modular, and scalable Discord bot built with discord.py. Featuring comprehensive logging, error handling, and a flexible architecture, MyDiscordBot is designed to provide seamless functionality for music playback, user leveling, moderation, and more. Whether you’re managing a small community or a large server, this bot ensures reliability and ease of maintenance.

📋 Table of Contents
	•	Features
	•	Project Structure
	•	Prerequisites
	•	Installation
	•	1. Clone the Repository
	•	2. Create and Activate a Virtual Environment
	•	3. Install Dependencies
	•	4. Install FFmpeg
	•	5. Set Up PostgreSQL Database
	•	6. Configure the Bot
	•	Running the Bot
	•	Using the Bot
	•	Music Commands
	•	Moderation Commands
	•	Utility Commands
	•	Logging
	•	Contributing
	•	License
	•	Support

🌟 Features
	•	Music Playback: Play, pause, resume, skip, and manage a queue of songs from YouTube.
	•	User Leveling: Track and display user levels and experience points.
	•	Moderation Tools: Kick, ban, and mute users with ease.
	•	Custom Help Command: Provides detailed information on available commands.
	•	Comprehensive Logging: Detailed logs for monitoring and debugging.
	•	Scalable Architecture: Modular design using cogs for easy feature additions.

📂 Project Structure

A well-organized project structure enhances maintainability and scalability. Here’s the recommended layout for MyDiscordBot:

my_discord_bot/
├── bot.py
├── cogs/
│   ├── __init__.py
│   ├── music.py
│   ├── leveling.py
│   ├── moderation.py
│   └── help.py
├── logs/
│   ├── bot.log
│   └── error.log
├── config/
│   └── config.yaml
├── requirements.txt
└── README.md

	•	bot.py: The main entry point of the bot.
	•	cogs/: Directory containing all cog modules, each handling specific functionalities.
	•	logs/: Directory to store log files (bot.log for general logs and error.log for error-specific logs).
	•	config/config.yaml: Configuration file to store sensitive information and settings.
	•	requirements.txt: Lists all Python dependencies required for the bot.
	•	README.md: Documentation for your bot.

⚙️ Prerequisites

Before setting up the bot, ensure you have the following installed:
	•	Python 3.11+: Download Python
	•	FFmpeg: Required for audio playback.
	•	Windows: FFmpeg Downloads
	•	macOS: Install via Homebrew

brew install ffmpeg


	•	Linux (Debian/Ubuntu):

sudo apt update
sudo apt install ffmpeg


	•	PostgreSQL: For managing user leveling data.
	•	Installation Guide: PostgreSQL Downloads

📥 Installation

Follow these steps to set up MyDiscordBot on your machine.

1. Clone the Repository

Clone the repository to your local machine using Git:

git clone https://github.com/yourusername/my_discord_bot.git
cd my_discord_bot

Replace yourusername with your actual GitHub username.

2. Create and Activate a Virtual Environment

It’s recommended to use a virtual environment to manage dependencies and avoid conflicts.

# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate the virtual environment
# On Windows:
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate

3. Install Dependencies

Install all required Python packages using pip:

pip install -r requirements.txt

4. Install FFmpeg

Ensure FFmpeg is installed and accessible via your system’s PATH.
	•	Windows:
	1.	Download FFmpeg from FFmpeg Downloads.
	2.	Extract the downloaded files.
	3.	Add the bin directory to your system’s PATH environment variable.
	•	macOS:

brew install ffmpeg


	•	Linux (Debian/Ubuntu):

sudo apt update
sudo apt install ffmpeg



5. Set Up PostgreSQL Database
	1.	Install PostgreSQL: Follow the official installation guide.
	2.	Create a Database and User:

sudo -u postgres psql

Inside the PostgreSQL shell:

CREATE DATABASE mydatabase;
CREATE USER myuser WITH ENCRYPTED PASSWORD 'mypassword';
GRANT ALL PRIVILEGES ON DATABASE mydatabase TO myuser;
\q

Replace mydatabase, myuser, and mypassword with your desired database name, username, and password.

6. Configure the Bot

Create and edit the config/config.yaml file with your bot’s configuration details.

# config/config.yaml

DISCORD_TOKEN: "YOUR_DISCORD_BOT_TOKEN_HERE"
COMMAND_PREFIX: "!"
LOG_LEVEL: "DEBUG"  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

Important:
	•	Replace "YOUR_DISCORD_BOT_TOKEN_HERE" with your actual Discord bot token. You can obtain this from the Discord Developer Portal.
	•	Ensure that the config/config.yaml file is not tracked by version control to protect sensitive information. Add config/config.yaml to your .gitignore file.

Update Database Connection in Leveling Cog

Edit cogs/leveling.py to include your PostgreSQL connection details.

# cogs/leveling.py

self.pool = await asyncpg.create_pool(dsn="postgresql://myuser:mypassword@localhost:5432/mydatabase")

Replace myuser, mypassword, and mydatabase with your actual PostgreSQL credentials.

🚀 Running the Bot

After completing the installation and configuration steps, you can start the bot.
	1.	Activate the Virtual Environment (if not already activated):

# On Windows:
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate


	2.	Run the Bot:

python bot.py

Upon successful launch, you should see log messages indicating that the bot is online and all cogs have been loaded.

🛠️ Using the Bot

Interact with your bot using the defined commands. All commands use the prefix defined in config/config.yaml (default is !).

🎵 Music Commands
	•	!play <song name or URL>: Plays a song from YouTube.
	•	!pause: Pauses the currently playing song.
	•	!resume: Resumes a paused song.
	•	!skip: Skips the currently playing song.
	•	!stop: Stops the music and clears the queue.
	•	!queue: Displays the current song queue.
	•	!now: Shows the currently playing song.
	•	!volume <0-100>: Adjusts the playback volume.
	•	!remove <song number>: Removes a song from the queue by its position number.
	•	!loop: Toggles looping of the current song.
	•	!shuffle: Shuffles the current song queue.
	•	!lyrics: Fetches lyrics for the currently playing song.

🔨 Moderation Commands

Note: These commands require administrator permissions.
	•	!kick @user [reason]: Kicks a user from the server.
	•	!ban @user [reason]: Bans a user from the server.
	•	!mute @user [duration in seconds] [reason]: Mutes a user for a specified duration.

📊 Utility Commands
	•	!help: Displays a comprehensive help message with all available commands.
	•	!profile: Displays your current level and experience points.

📝 Logging

Logging is essential for monitoring the bot’s activity and diagnosing issues.
	•	Log Files: All logs are stored in the logs/ directory.
	•	bot.log: Contains general logs, including command executions and informational messages.
	•	error.log: Captures error-specific logs for easier troubleshooting.
	•	Log Levels:
	•	DEBUG: Detailed information, typically of interest only when diagnosing problems.
	•	INFO: Confirmation that things are working as expected.
	•	WARNING: An indication that something unexpected happened.
	•	ERROR: Due to a more serious problem, the software has not been able to perform some function.
	•	CRITICAL: A serious error, indicating that the program itself may be unable to continue running.

You can adjust the logging level in config/config.yaml by modifying the LOG_LEVEL parameter.

🤝 Contributing

Contributions are welcome! To contribute:
	1.	Fork the Repository: Click the “Fork” button at the top right of the repository page.
	2.	Create a New Branch:

git checkout -b feature/YourFeatureName


	3.	Commit Your Changes:

git commit -m "Add your message here"


	4.	Push to the Branch:

git push origin feature/YourFeatureName


	5.	Open a Pull Request: Navigate to your forked repository and click “Compare & pull request.”

Please ensure that your code adheres to the existing coding standards and includes appropriate logging and error handling.

📄 License

This project is licensed under the MIT License.

📬 Support

If you encounter any issues or have questions, feel free to open an issue on the repository or contact the maintainer directly.

Happy Botting! 🎉🤖