# SuperAlpha Do

> SuperAlpha Do -- Alpha Branch

SuperAlpha Do is the open-source development repository for **SuperAlpha Do**, a multi-purpose Discord bot built on discord.py. This branch serves as the staging area for experimental features, new modules, and community-driven testing before code reaches the stable release.


Support server - https://discord.gg/Z2NXkwkFK3
---

## Requirements

- Python 3.14
- discord.py 2.7.x
- python-dotenv
- aiohttp
- py-cord or compatible fork (if extending)
- Groq API key (for AI commands) -- https://console.groq.com/keys
- FFmpeg (for music playback)
- Davey (for joining voice chats and playing music)

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

# Optional -- enables GitHub issue linking on the suggestion board
GITHUB_TOKEN='your-github-token-here'

# Optional -- overrides for server links / branding (defaults apply if unset)
INVITE_URL='https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID'
SUPPORT_SERVER='https://discord.gg/YOUR_INVITE'
OWNER_HANDLE='@your_handle'
GIT_REPO='yourname/SuperAlpha-Do'
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
| `GITHUB_TOKEN`   | No       | GitHub token enabling issue linking on the suggestion board |
| `INVITE_URL`     | No       | Bot invite URL (overrides the built-in default)             |
| `SUPPORT_SERVER` | No       | Support server invite link (overrides the built-in default) |
| `OWNER_HANDLE`   | No       | Owner handle shown on the invite command (e.g. `@r4ve_x`)    |
| `GIT_REPO`       | No       | Repo slug used by `alpha git`, e.g. `guptamaan/SuperAlpha-Do` |

Per-guild configuration and per-user data are stored under the `data/` directory (gitignored). The bot creates subdirectories and SQLite databases as needed when commands are used.

---

## How do we name updates?
The updates are named using the following format - year.month.date
If the update is the first update of the day then it is simply the year.month.date and the succeeding updates have letter paired with the date in alphabetical order

E.g. For the first update of the date 1/1/2027 the update will be - 27.1.1

And for the second update on the same date will be 27.1.1A

For third - 27.1.1B and so on


At most the bot is only updated thrice a day, while the stable branch updates once or twice a *Month*.

---

## Usage

**Prefix:** `alpha ` or `Alpha ` (with a trailing space).
Slash commands and bot-mention pings are also accepted as a prefix.

**Built-in help:** `alpha man` lists all commands grouped by module. `alpha man <command>` displays a detailed manual page for that command. `alpha man <words>` searches commands by name, alias, and function keywords, opening an interactive results menu.

**Shell-style goodies:** type an unknown command and the bot suggests the closest match bash-style (`Did you mean: X?  (y/n/hint)`). `alpha history` (or `alpha hist`) lists your numbered command history, `alpha !!` re-runs your last command, and `alpha !<line>` / `alpha !<keyword>` re-run a specific past command.

### Feature flags

Three optional features are disabled by default and must be enabled per server:

| Feature  | Enable                       | Disable                      |
|----------|------------------------------|------------------------------|
| Linux    | `alpha enable linux`         | `alpha disable linux`        |
| Automod  | `alpha enable automod`       | `alpha disable automod`      |
| Distro   | `alpha enable distro`        | `alpha disable distro`       |

Once enabled, the corresponding commands and aliases become available to all users in that server.

---

## Modules

### System
Ping, latency, uptime, server status, live health dashboard (htop), cog management, bot invite link, latest code pushes (`alpha git`), and a searchable manual (`alpha man <words>`).

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

### Suggestion Board
Members submit ideas with `alpha suggest <idea>`, which posts a board message with an upvote/downvote discussion thread. Track ideas through statuses (open, approved, rejected, implemented, archived) and manage the board with `alpha suggestion <action>`. With a `GITHUB_TOKEN` set, suggestions can be linked to GitHub issues (`alpha suggestion link` / `alpha suggestion repo`).

### Spam Chain
A cooperative chat game where members take turns sending the same word or emoji to build a streak. Sending it twice in a row or sending something else breaks the chain.

### Distro Guess
A guessing game where the bot randomly posts a Linux distro image (from the `distro/` folder) into a channel. The first member to correctly name the distro wins XP and SP, and the image is removed. Drop images into `distro/` named after the distro with a `.png` extension and without `os`/`linux` in the name (e.g. `arch.png`, `ubuntu.png`). Matching picks up the filename the bot is showing and is case-insensitive; guesses with `os`, `linux`, or `os linux` appended (e.g. `arch os`, `Arch Linux`) are all accepted.

Each distro can have an entry in `distro/names.json` giving it a difficulty tier (`easy` / `medium` / `hard`) and up to two hints (e.g. package manager, base system, or origin). Base rewards scale with tier: Easy 15 XP + 3 SP, Medium 25 XP + 5 SP, Hard 45 XP + 10 SP. Rounds drop a hint 45 seconds and 150 seconds after spawning, each one cutting the reward by 40%; unanswered rounds auto-expire after 180 seconds and reveal the answer. Wrong guesses are throttled to one per ~2.5 seconds per member to stop guess-spamming. Disabled by default -- enable with `alpha enable distro`. Spawn a round manually with `alpha distro spawn`.

Admins can pin round spawns to a specific channel with `alpha distro channel #channel`, view the current target with `alpha distro channel`, and revert to random channels with `alpha distro channel clear`.

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
Server-wide activity journal with a `journalctl` interface, plus per-user bash-style command history: `history`/`hist`, `!!` (re-run last), and `!<line>` / `!<keyword>` re-runs.

### Linux
Optional Linux/Arch-inspired command aliases. Enable with `alpha enable linux` to activate aliases like `neofetch`, `whoami`, `pacman`, `htop`, and dozens more across all modules.

---

## Project status

This repository is under active development. Features may be incomplete, renamed, or removed without notice. For the stable release, use SuperAlpha Do (closed source).

---

## License

See the LICENSE file in the repository root for details.
