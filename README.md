# SuperAlpha Do

> SuperUser DO -- Alpha Branch

SuperAlpha Do is the open-source development repository for **SuperUser DO**, a multi-purpose Discord bot built on discord.py. This branch serves as the staging area for experimental features, new modules, and community-driven testing before code reaches the stable release.

---

## Requirements

- Python 3.14
- discord.py 2.7.x
- python-dotenv
- aiohttp
- py-cord or compatible fork (if extending)
- Groq API key (for AI commands) -- https://console.groq.com/keys
- FFmpeg (for music playback)

All Python dependencies are listed in `requirements.txt` and can be installed with:

```
pip install -r requirements.txt
```

---

## Setup

1. Clone the repository:
```
git clone https://github.com/guptamaan/SuperAlpha-Do.git
cd SuperAlpha-Do
```

2. Install dependencies:
```
pip install -r requirements.txt
```

3. Create a `.env` file in the project root (this file is gitignored):
```
DISCORD_TOKEN='your-bot-token-here'

# Optional -- required only for AI commands
GROQ_API_KEY='your-groq-api-key-here'
GROQ_MODEL='your-chosen-model'
```

4. Start the bot:
```
python3 main.py
```

---

## Configuration

| Key              | Required | Description                                      |
|------------------|----------|--------------------------------------------------|
| `DISCORD_TOKEN`  | Yes      | Discord bot token from the Developer Portal      |
| `GROQ_API_KEY`   | No       | API key for Groq-hosted LLM (AI commands)        |
| `GROQ_MODEL`     | No       | Model identifier for Groq (e.g. `llama-3.3-70b-versatile`) |

Per-guild configuration is stored as JSON under the `data/` directory (gitignored). The bot creates subdirectories as needed when commands are used.

---

## Usage

**Prefix:** `alpha ` or `Alpha ` (with a trailing space).
Slash commands and bot-mention pings are also accepted as prefix.

**Built-in help:** `alpha man` lists all commands grouped by module. `alpha man <command>` displays a detailed manual page for that command.

### Feature flags

Two optional features are disabled by default and must be enabled per server:

| Feature  | Enable                       | Disable                      |
|----------|------------------------------|------------------------------|
| Linux    | `alpha enable linux`         | `alpha disable linux`        |
| Automod  | `alpha enable automod`       | `alpha disable automod`      |

Once enabled, the corresponding commands and aliases become available to all users in that server.

---

## Modules

### System
Ping, latency, uptime, server status, live health dashboard (htop), cog management, bot invite link.

### Moderation
Kick, ban, softban, mass ban, unban, mute/unmute, deafen, role management, message purge, warning system, slowmode.

### AI
Conversational AI via Groq, image generation, code generation, translation, summarization, conversation history.

### Music
YouTube playback, queue management, shuffle, loop, volume control, replay, radio streams, autoplay.

### XP / Economy
Per-user XP and SP (spendable points) system, level-up notifications, leaderboard, daily/work/bet commands, SP economy shop with custom roles.

### Info
User, server, role, channel, and bot information commands.

### Fun
8-ball, coin flip, dice roll, trivia, jokes, ASCII art, mock text, reverse text, rock-paper-scissors, slots, would-you-rather, ship calculator.

### Games
Tic-tac-toe, Connect 4, Word Bank (hangman-style word guessing).

### Utility
Polls, reminders, calculator, random number generator, wiki lookup, base64, hash, timestamps, weather, urban dictionary, dictionary, URL shortener, translation.

### Music Games
Guess-the-song challenge.

### Clans
Create, join, leave clans; clan challenges, attacks, missions, treasury, leaderboard.

### Auto-moderation
Word filter, link whitelist (with phishing detection), mass-mention protection. Configurable per server with a strike system that escalates to timeouts. Disabled by default -- enable with `alpha enable automod`.

### Giveaways
Create reaction-entry giveaways with configurable duration, winner count, and automatic end timers. Persists across restarts.

### Economy Shop
Spend SP on custom roles with user-managed name and color. Admin-configurable item list per server.

### Spam Chain
A cooperative chat game where members take turns sending the same word or emoji to build a streak. Sending it twice in a row or sending something else breaks the chain.

### Welcome / Logging
Welcome and goodbye messages, audit log forwarding to a designated channel.

### Reaction Roles
Self-assignable roles via reaction messages.

### Temporary Voice Channels
On-demand voice channel creation.

### AFK
AFK status tracking with mentions-on-return notifications.

### Spectrum
Color spectrum commands.

### Journal
Server journal with `journalctl` interface.

### Linux
Optional Linux/Arch-inspired command aliases. Enable with `alpha enable linux` to activate aliases like `neofetch`, `whoami`, `pacman`, `htop`, and dozens more across all modules.

---

## Project status

This repository is under active development. Features may be incomplete, renamed, or removed without notice. For the stable release, see the main SuperUser DO repository.

---

## License

See the LICENSE file in the repository root for details.
