"""
cogs/fun.py — Fun & entertainment commands.
Commands: 8ball, coinflip, roll, rps, joke, quote, ascii, mock, reverse,
          choose, ship, hack, trivia, fact, pat, kill, slots, wouldyourather,
          emojify, fliptext
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import cast
import random
import asyncio
import aiohttp
import math


EIGHT_BALL_RESPONSES = [
    ("It is certain.", 0x2ECC71),
    ("It is decidedly so.", 0x27AE60),
    ("Without a doubt.", 0x1ABC9C),
    ("Yes, definitely.", 0x00D4AA),
    ("You may rely on it.", 0x3498DB),
    ("As I see it, yes.", 0x2980B9),
    ("Most likely.", 0x9B59B6),
    ("Outlook good.", 0x8E44AD),
    ("Yes.", 0xF39C12),
    ("Signs point to yes.", 0xE67E22),
    ("Reply hazy, try again.", 0x95A5A6),
    ("Ask again later.", 0x7F8C8D),
    ("Better not tell you now.", 0xBDC3C7),
    ("Cannot predict now.", 0x566573),
    ("Concentrate and ask again.", 0x566573),
    ("Don't count on it.", 0xE74C3C),
    ("My reply is no.", 0xC0392B),
    ("My sources say no.", 0xA93226),
    ("Outlook not so good.", 0x922B21),
    ("Very doubtful.", 0x7B241C),
]

RPS_CHOICES = ["rock", "paper", "scissors"]
RPS_WINS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
RPS_ICONS = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

TRIVIA_QUESTIONS = [
    {"q": "What is the capital of Japan?", "a": "Tokyo", "c": "Japan"},
    {"q": "What is 2 + 2?", "a": "4", "c": "Math"},
    {"q": "Who wrote Romeo and Juliet?", "a": "Shakespeare", "c": "Literature"},
    {"q": "What planet is known as the Red Planet?", "a": "Mars", "c": "Space"},
    {"q": "What is the largest ocean?", "a": "Pacific", "c": "Geography"},
    {"q": "What year did WWII end?", "a": "1945", "c": "History"},
    {"q": "What is the chemical symbol for gold?", "a": "Au", "c": "Chemistry"},
    {"q": "Who painted the Mona Lisa?", "a": "Da Vinci", "c": "Art"},
    {"q": "What is the hardest natural substance?", "a": "Diamond", "c": "Science"},
    {"q": "What country has the most pyramids?", "a": "Sudan", "c": "Geography"},
]

FUN_FACTS = [
    "Honey never spoils! Archaeologists have found 3000-year-old honey in Egyptian tombs.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries aren't.",
    "The Eiffel Tower can grow up to 15 cm taller in summer.",
    "Sharks existed before trees.",
    "A group of flamingos is called a 'flamboyance'.",
    "The shortest war in history lasted 38-45 minutes.",
    "Cows have best friends and get stressed when separated.",
    "Lightning strikes Earth about 8 million times per day.",
    "A jiffy is an actual unit of time: 1/100th of a second.",
    "The inventor of the Pringles can is buried in one.",
]


class Fun(commands.Cog, name="fun"):
    """Fun and entertainment commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._trivia_scores: dict[int, int] = {}

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self._session:
            await self._session.close()

    def _make_embed(self, title: str, color: int) -> discord.Embed:
        return discord.Embed(color=color).set_author(
            name=title, icon_url=None
        )

    # ── 8ball ─────────────────────────────────────────────────────────────────
    @commands.command(name="8ball", aliases=["eightball"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def eight_ball(self, ctx: commands.Context, *, question: str) -> None:
        """Ask the Magic 8-Ball for answers. Usage: sudo 8ball <question>"""
        response, color = random.choice(EIGHT_BALL_RESPONSES)
        embed = discord.Embed(color=color)
        embed.set_author(name="🎱 Magic 8-Ball", icon_url=None)
        embed.add_field(name="❓ Question", value=f"*{question}*", inline=False)
        embed.add_field(name="✨ Answer", value=response, inline=False)
        embed.set_footer(text=f"Asked by {ctx.author}")
        await ctx.send(embed=embed)

    # ── coinflip ──────────────────────────────────────────────────────────────
    @commands.command(name="coinflip", aliases=["flip", "coin"])
    async def coinflip(self, ctx: commands.Context) -> None:
        """Flip a coin to get heads or tails. Usage: sudo coinflip"""
        result, emoji, color = random.choice([
            ("Heads", "🪙", 0xF1C40F),
            ("Tails", "🪙", 0x3498DB),
        ])
        embed = self._make_embed("🪙 Coin Flip", color)
        embed.description = f"# {emoji} **{result}!**"
        embed.set_footer(text=f"Flipped by {ctx.author}")
        await ctx.send(embed=embed)

    # ── roll ──────────────────────────────────────────────────────────────────
    @commands.command(name="roll", aliases=["dice", "rng"])
    async def roll(self, ctx: commands.Context, dice: str = "1d6") -> None:
        """Roll dice in NdM format. Usage: sudo roll [NdM] (e.g. sudo roll 2d20)"""
        try:
            n_str, m_str = dice.lower().split("d")
            n, m = int(n_str or 1), int(m_str)
            if not (1 <= n <= 20 and 2 <= m <= 1000):
                raise ValueError
        except ValueError:
            embed = self._make_embed("🎲 Dice Error", 0xE74C3C)
            embed.description = "❌ Invalid format. Use `NdM` (e.g. `2d20`)"
            await ctx.send(embed=embed)
            return

        rolls = [random.randint(1, m) for _ in range(n)]
        total = sum(rolls)

        embed = self._make_embed("🎲 Dice Roll", 0x2ECC71)
        embed.add_field(name="Roll", value=f"`{dice}`", inline=True)
        embed.add_field(name="Results", value=" + ".join(f"`{r}`" for r in rolls), inline=False)
        embed.add_field(name="**Total**", value=f"# {total}", inline=False)
        embed.set_footer(text=f"Rolled by {ctx.author}")
        await ctx.send(embed=embed)

    # ── rps ───────────────────────────────────────────────────────────────────
    @commands.command(name="rps")
    async def rps(self, ctx: commands.Context, choice: str) -> None:
        """Play Rock Paper Scissors against the bot. Usage: sudo rps <rock|paper|scissors>"""
        choice = choice.lower()
        if choice not in RPS_CHOICES:
            embed = self._make_embed("🎮 RPS Error", 0xE74C3C)
            embed.description = "❌ Choose **rock**, **paper**, or **scissors**"
            await ctx.send(embed=embed)
            return

        bot_choice = random.choice(RPS_CHOICES)
        user_icon = RPS_ICONS[choice]
        bot_icon = RPS_ICONS[bot_choice]

        if choice == bot_choice:
            result, result_color = "🤝 It's a tie!", 0xF39C12
        elif RPS_WINS[choice] == bot_choice:
            result, result_color = "🎉 You win!", 0x2ECC71
        else:
            result, result_color = "💀 You lose!", 0xE74C3C

        embed = discord.Embed(color=result_color)
        embed.set_author(name="✊✋✌️ Rock Paper Scissors", icon_url=None)
        embed.add_field(name=f"You {user_icon}", value=f"**{choice.title()}**", inline=True)
        embed.add_field(name="VS", value="⚔️", inline=True)
        embed.add_field(name=f"Bot {bot_icon}", value=f"**{bot_choice.title()}**", inline=True)
        embed.add_field(name="Result", value=f"# {result}", inline=False)
        await ctx.send(embed=embed)

    # ── joke ──────────────────────────────────────────────────────────────────
    @commands.command(name="joke")
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def joke(self, ctx: commands.Context) -> None:
        """Get a random programming joke. Usage: sudo joke"""
        url = "https://v2.jokeapi.dev/joke/Programming?blacklistFlags=nsfw,racist,sexist"
        try:
            assert self._session is not None
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
            if data.get("type") == "single":
                text = data["joke"]
            else:
                text = f"{data['setup']}\n\n||{data['delivery']}||"
        except Exception:
            text = "Why do programmers prefer dark mode?\nBecause light attracts bugs!"

        embed = discord.Embed(title="😄 Programming Joke", description=text, color=0xF1C40F)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── quote ─────────────────────────────────────────────────────────────────
    @commands.command(name="quote", aliases=["inspire"])
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def quote(self, ctx: commands.Context) -> None:
        """Get an inspirational quote. Usage: sudo quote"""
        try:
            assert self._session is not None
            async with self._session.get(
                "https://zenquotes.io/api/random",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json()
            if not data:
                raise ValueError("Empty response from API")
            quote_text = data[0]["q"]
            author = data[0]["a"]
        except Exception:
            quote_text = "The best error message is the one that never shows up."
            author = "Thomas Fuchs"

        embed = discord.Embed(description=f"❝ *{quote_text}* ❞", color=0x1ABC9C)
        embed.set_author(name=f"💭 — {author}", icon_url=None)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── ascii ─────────────────────────────────────────────────────────────────
    @commands.command(name="ascii", aliases=["figlet"])
    async def ascii_art(self, ctx: commands.Context, *, text: str) -> None:
        """Convert text to ASCII art. Usage: sudo ascii <text> (max 20 chars)"""
        if len(text) > 20:
            embed = self._make_embed("🎨 ASCII Error", 0xE74C3C)
            embed.description = "❌ Text too long (max 20 characters)"
            await ctx.send(embed=embed)
            return
        try:
            import pyfiglet
            art = pyfiglet.figlet_format(text, font="slant")
        except ImportError:
            art = "\n".join(f"  {c.upper()}" for c in text)
        if len(art) > 1900:
            art = art[:1900] + "\n..."

        embed = self._make_embed("🎨 ASCII Art", 0x9B59B6)
        embed.description = f"```\n{art}\n```"
        embed.set_footer(text=f"Text: {text}")
        await ctx.send(embed=embed)

    # ── mock ──────────────────────────────────────────────────────────────────
    @commands.command(name="mock")
    async def mock(self, ctx: commands.Context, *, text: str) -> None:
        """Mock text with alternating capitalization. Usage: sudo mock <text>"""
        result = "".join(
            c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text)
        )
        embed = self._make_embed("📝 Mock Text", 0x2ECC71)
        embed.add_field(name="Original", value=f"~~{text}~~", inline=False)
        embed.add_field(name="Mocked", value=f"**{result}**", inline=False)
        await ctx.send(embed=embed)

    # ── reverse ───────────────────────────────────────────────────────────────
    @commands.command(name="reverse", aliases=["rev", "tac"])
    async def reverse(self, ctx: commands.Context, *, text: str) -> None:
        """Reverse any text. Usage: sudo reverse <text>"""
        reversed_text = text[::-1]
        embed = self._make_embed("🔄 Reverse Text", 0xE74C3C)
        embed.add_field(name="Original", value=text, inline=False)
        embed.add_field(name="Reversed", value=reversed_text, inline=False)
        await ctx.send(embed=embed)

    # ── choose ────────────────────────────────────────────────────────────────
    @commands.command(name="choose", aliases=["pick"])
    async def choose(self, ctx: commands.Context, *options: str) -> None:
        """Let the bot choose between options. Usage: sudo choose <option1> <option2> [option3...]"""
        if len(options) < 2:
            embed = self._make_embed("🎯 Choose Error", 0xE74C3C)
            embed.description = "❌ Provide at least 2 options"
            await ctx.send(embed=embed)
            return

        picked = random.choice(options)
        options_list = "\n".join(f"{'👉 ' if o == picked else '  '}`{o}`" for o in options)

        embed = self._make_embed("🎯 Decision Made", 0x9B59B6)
        embed.add_field(name="Options", value=options_list, inline=False)
        embed.add_field(name="Choice", value=f"# ✨ **{picked}**", inline=False)
        await ctx.send(embed=embed)

    # ── ship ─────────────────────────────────────────────────────────────────
    @commands.command(name="ship")
    async def ship(self, ctx: commands.Context, person1: str, person2: str) -> None:
        """Calculate love compatibility between two people. Usage: sudo ship <person1> <person2>"""
        love_score = random.randint(0, 100)
        bar_len = math.ceil(love_score / 10)
        bar = "❤️" * bar_len + "🖤" * (10 - bar_len)

        messages = [
            "They were meant for each other! 💕",
            "Could be a lovely couple! 💖",
            "There's definitely a spark! ✨",
            "Friendship is also beautiful! 😊",
            "Maybe not meant to be... 💔",
        ]
        msg_idx = min((love_score // 20), 4)
        message = messages[msg_idx]

        color = int(f"0x{hex(min(255, love_score * 2 + 50))[2:]:0>2}" + "0040", 16) if love_score > 50 else 0x9B59B6

        embed = discord.Embed(color=color)
        embed.set_author(name="💕 Love Meter", icon_url=None)
        embed.add_field(name="Couple", value=f"**{person1}** 💕 **{person2}**", inline=False)
        embed.add_field(name="Love Score", value=f"# {love_score}%", inline=True)
        embed.add_field(name="Meter", value=bar, inline=False)
        embed.add_field(name="Verdict", value=f"_{message}_", inline=False)
        await ctx.send(embed=embed)

    # ── hack ─────────────────────────────────────────────────────────────────
    @commands.command(name="hack")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def hack(self, ctx: commands.Context, target: discord.User | discord.Member | None = None) -> None:
        """Fake hack simulation (just for fun!). Usage: sudo hack [@user]"""
        target = target or ctx.author
        assert target is not None
        steps = [
            ("Initializing exploit kit...", "🔓"),
            ("Bypassing firewall...", "🛡️"),
            ("Injecting payload...", "💉"),
            ("Accessing database...", "📊"),
            ("Extracting passwords...", "🔑"),
            ("Covering tracks...", "🧹"),
            ("Hacking complete!", "✅"),
        ]

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="💻 Hack Mode", icon_url=None)
        msg = await ctx.send(embed=embed)

        for step, icon in steps[:-1]:
            await asyncio.sleep(1)
            embed = discord.Embed(color=0xF39C12)
            embed.set_author(name="💻 Hack Mode", icon_url=None)
            embed.add_field(name=f"{icon} {step}", value="▰" + "▱" * 9, inline=False)
            embed.set_footer(text=f"Target: {target}")
            await msg.edit(embed=embed)

        passwords = ["hunter2", "password123", "qwerty", "letmein", "admin"]
        ips = ["192.168.1.1", "10.0.0.1", "172.16.0.1"]
        email = f"{target.name}@gmail.com"

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="💻 Hack Complete", icon_url=None)
        embed.add_field(name="Target", value=f"**{target}**", inline=True)
        embed.add_field(name="Email", value=f"`{email}`", inline=True)
        embed.add_field(name="Password", value=f"`{random.choice(passwords)}`", inline=True)
        embed.add_field(name="IP Address", value=f"`{random.choice(ips)}`", inline=True)
        embed.add_field(name="Bank PIN", value=f"`{random.randint(1000, 9999)}`", inline=True)
        embed.set_footer(text="Just kidding 😜")
        await msg.edit(embed=embed)

    # ── trivia ───────────────────────────────────────────────────────────────
    @commands.command(name="trivia")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def trivia(self, ctx: commands.Context) -> None:
        """Test your knowledge with a trivia question. Usage: sudo trivia"""
        q = random.choice(TRIVIA_QUESTIONS)
        self._trivia_scores[ctx.author.id] = 0

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name="🧠 Trivia Time!", icon_url=None)
        embed.add_field(name="Category", value=f"`{q['c']}`", inline=True)
        embed.add_field(name="Question", value=f"**{q['q']}**", inline=False)
        embed.set_footer(text="DM the answer to the bot!")

        def check(m):
            return m.author == ctx.author and m.guild is None

        await ctx.send(embed=embed)
        try:
            answer_msg = await self.bot.wait_for("message", timeout=15.0, check=check)
            answer = answer_msg.content.lower().strip()

            if answer == q["a"].lower() or q["a"].lower() in answer:
                self._trivia_scores[ctx.author.id] = self._trivia_scores.get(ctx.author.id, 0) + 1
                embed = discord.Embed(color=0x2ECC71, description="✅ **Correct!** Well done!")
            else:
                embed = discord.Embed(color=0xE74C3C, description=f"❌ Wrong! The answer was **{q['a']}**")
            embed.set_footer(text=f"Score: {self._trivia_scores[ctx.author.id]} points")
            await ctx.send(embed=embed)
        except asyncio.TimeoutError:
            embed = discord.Embed(color=0x95A5A6, description=f"⏰ Time's up! The answer was **{q['a']}**")
            await ctx.send(embed=embed)

    # ── fact ─────────────────────────────────────────────────────────────────
    @commands.command(name="fact", aliases=["didyouknow", "dyk"])
    async def fact(self, ctx: commands.Context) -> None:
        """Learn a random fun fact. Usage: sudo fact"""
        fact = random.choice(FUN_FACTS)
        embed = discord.Embed(color=0x1ABC9C)
        embed.set_author(name="💡 Did You Know?", icon_url=None)
        embed.description = f"**{fact}**"
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── pat ──────────────────────────────────────────────────────────────────
    @commands.command(name="pat")
    async def pat(self, ctx: commands.Context, member: discord.Member = None) -> None:
        """Pat someone with a cute penguin! Usage: sudo pat [@user]"""
        if not member:
            embed = self._make_embed("❌ No Target", 0xE74C3C)
            embed.description = "Mention someone to pat!"
            await ctx.send(embed=embed)
            return
        
        if member.id == ctx.author.id:
            embed = self._make_embed("❌ Nope", 0xE74C3C)
            embed.description = "You can't pat yourself!"
            await ctx.send(embed=embed)
            return
        
        try:
            if isinstance(ctx.channel, discord.TextChannel):
                webhook = await ctx.channel.create_webhook(name="sudo")
                await webhook.send(
                    f"{ctx.author.mention} pats {member.mention} UwU\n<a:tuxpat:1485238409437118556>",
                    username=ctx.bot.user.name,
                    avatar_url=ctx.bot.user.display_avatar.url,
                )
                await webhook.delete()
        except discord.Forbidden:
            await ctx.send(f"{ctx.author.mention} pats {member.mention} UwU\n<a:tuxpat:1485238409437118556>")
        try:
            await ctx.message.delete()
        except:
            pass

    # ── kill ─────────────────────────────────────────────────────────────────
    @commands.command(name="kill")
    async def kill(self, ctx: commands.Context, *, victim: str | None = None) -> None:
        """Playfully eliminate someone. Usage: sudo kill <victim name>"""
        kills = [
            "was struck by a falling piano! 🎹",
            "was eaten by a horde of cats! 🐱",
            "tripped over their own shoelaces! 👟",
            "was eliminated by a ninja! 🥷",
            "fell into a pit of rubber ducks! 🦆",
            "was pranked to death! 😈",
            "was defeated by a rubber band! 🎯",
            "was lost in the void! 🌀",
        ]
        victim = victim or "someone"
        embed = self._make_embed("💀 Elimination", 0xE74C3C)
        embed.description = f"**{victim}** {random.choice(kills)}"
        await ctx.send(embed=embed)

    # ── slots ─────────────────────────────────────────────────────────────────
    @commands.command(name="slots", aliases=["slotmachine"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def slots(self, ctx: commands.Context, bet: int = 100) -> None:
        """Play the slot machine game. Usage: sudo slots [bet amount]"""
        if bet < 1:
            bet = 100

        emojis = ["🍎", "🍊", "🍋", "🍇", "🍉", "🍒", "💎", "7️⃣"]
        weights = [30, 25, 20, 15, 5, 3, 1, 1]
        total_weight = sum(weights)

        def weighted_choice():
            r = random.randint(1, total_weight)
            for i, w in enumerate(weights):
                r -= w
                if r <= 0:
                    return emojis[i]
            return emojis[0]

        results = [weighted_choice() for _ in range(3)]
        unique_results = set(results)

        if len(unique_results) == 1:
            if results[0] == "7️⃣":
                result_text = "JACKPOT! 🎉"
                color = 0xFFD700
                multiplier = 10
            elif results[0] == "💎":
                result_text = "DIAMOND WIN! 💎"
                color = 0x00FFFF
                multiplier = 5
            else:
                result_text = "TRIPLE MATCH! 🎊"
                color = 0x2ECC71
                multiplier = 3
        elif len(unique_results) == 2:
            result_text = "Nice! Two matching! 🍀"
            color = 0x3498DB
            multiplier = 1
        else:
            result_text = "No match. Try again! 🎰"
            color = 0xE74C3C
            multiplier = 0

        slots_display = " | ".join(results)
        embed = discord.Embed(color=color)
        embed.set_author(name="🎰 Slot Machine", icon_url=None)
        embed.description = f"```\n  {slots_display}\n```"
        embed.add_field(name="Result", value=f"# {result_text}", inline=False)
        embed.add_field(name="Bet", value=f"{bet} coins", inline=True)
        if multiplier > 0:
            winnings = bet * multiplier
            embed.add_field(name="Winnings", value=f"+{winnings} coins", inline=True)
        embed.set_footer(text=f"Spun by {ctx.author}")
        await ctx.send(embed=embed)

    # ── wouldyourather ─────────────────────────────────────────────────────────
    @commands.command(name="wouldyourather", aliases=["wyr"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def wouldyourather(self, ctx: commands.Context) -> None:
        """Get a would you rather question. Usage: sudo wouldyourather"""
        questions = [
            ("Be able to fly", "Be invisible"),
            ("Live without music", "Live without movies"),
            ("Have a rewind button for your life", "Have a pause button"),
            ("Be famous", "Be the best friend of someone famous"),
            ("Have unlimited money", "Have unlimited love"),
            ("Be the strongest person", "Be the smartest person"),
            ("Travel the world", "Learn every language"),
            ("Never use social media again", "Never watch TV again"),
            ("Have a personal chef", "Have a personal driver"),
            ("Live in the ocean", "Live on the moon"),
            ("Be able to read minds", "Be able to see the future"),
            ("Give up your phone", "Give up your bed"),
            ("Always be 10 minutes late", "Always be 20 minutes early"),
            ("Have no taste buds", "Have no sense of smell"),
            ("Be a famous actor", "Be a famous musician"),
        ]

        opt1, opt2 = random.choice(questions)

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🤔 Would You Rather?", icon_url=None)
        embed.add_field(name="Option 1", value=f"**{opt1}**", inline=False)
        embed.add_field(name="Option 2", value=f"**{opt2}**", inline=False)
        embed.set_footer(text=f"Answer with 👍 for option 1 or 👎 for option 2")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    # ── emojify ────────────────────────────────────────────────────────────────
    @commands.command(name="emojify")
    async def emojify(self, ctx: commands.Context, *, text: str) -> None:
        """Convert text to emoji letters. Usage: sudo emojify <text> (max 50 chars)"""
        if len(text) > 50:
            embed = self._make_embed("😵 Too Long", 0xE74C3C)
            embed.description = "Text must be under 50 characters"
            await ctx.send(embed=embed)
            return

        emoji_map = {
            'a': '🅰️', 'b': '🅱️', 'c': '🇨', 'd': '🇩', 'e': '🇪', 'f': '🇫',
            'g': '🇬', 'h': '🇭', 'i': '🇮', 'j': '🇯', 'k': '🇰', 'l': '🇱',
            'm': '🇲', 'n': '🇳', 'o': '🅾️', 'p': '🇵', 'q': '🇶', 'r': '🇷',
            's': '🇸', 't': '🇹', 'u': '🇺', 'v': '🇻', 'w': '🇼', 'x': '🇽',
            'y': '🇾', 'z': '🇿',
            '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
            '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣',
            '!': '❗', '?': '❓', '$': '💰', '+': '➕', '-': '➖',
        }

        result = []
        for char in text.lower():
            if char in emoji_map:
                result.append(emoji_map[char])
            elif char == ' ':
                result.append('  ')
            else:
                result.append(char)

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name="😀 Emojified!", icon_url=None)
        embed.add_field(name="Original", value=f"`{text}`", inline=False)
        embed.add_field(name="Emojified", value="".join(result), inline=False)
        await ctx.send(embed=embed)

    # ── fliptext ────────────────────────────────────────────────────────────────
    @commands.command(name="fliptext", aliases=["upside"])
    async def fliptext(self, ctx: commands.Context, *, text: str) -> None:
        """Flip text upside down. Usage: sudo fliptext <text>"""
        if len(text) > 100:
            text = text[:100]

        flip_map = {
            'a': 'ɐ', 'b': 'q', 'c': 'ɔ', 'd': 'p', 'e': 'ǝ', 'f': 'ɟ',
            'g': 'ƃ', 'h': 'ɥ', 'i': 'ᴉ', 'j': 'ɾ', 'k': 'ʞ', 'l': 'l',
            'm': 'ɯ', 'n': 'u', 'o': 'o', 'p': 'd', 'q': 'b', 'r': 'ɹ',
            's': 's', 't': 'ʇ', 'u': 'n', 'v': 'ʌ', 'w': 'ʍ', 'x': 'x',
            'y': 'ʎ', 'z': 'z',
            'A': '∀', 'B': 'ꓭ', 'C': 'Ɔ', 'D': 'ᗡ', 'E': 'Ǝ', 'F': 'Ⅎ',
            'G': '⅁', 'H': 'H', 'I': 'I', 'J': 'ſ', 'K': 'ꓘ', 'L': '˥',
            'M': 'W', 'N': 'N', 'O': 'O', 'P': 'Ԁ', 'Q': 'Ꝺ', 'R': 'ꓤ',
            'S': 'S', 'T': '⊥', 'U': '∩', 'V': 'Λ', 'W': 'M', 'X': 'X',
            'Y': '⅄', 'Z': 'Z',
            '1': 'Ɩ', '2': 'ᄅ', '3': 'Ɛ', '4': 'ㄣ', '5': 'ϛ', '6': '9',
            '7': 'ㄥ', '8': '8', '9': '6', '0': '0',
            '.': '˙', ',': '\'', '"': '„', '\'': ',', '!': '¡', '?': '¿',
            ' ': ' ',
        }

        flipped = ''.join(flip_map.get(c, c) for c in reversed(text))

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🔄 Flipped Text", icon_url=None)
        embed.add_field(name="Original", value=f"`{text}`", inline=False)
        embed.add_field(name="Flipped", value=f"`{flipped}`", inline=False)
        await ctx.send(embed=embed)

    # ── Slash Commands ────────────────────────────────────────────────────────
    @app_commands.command(name="8ball", description="Ask the Magic 8-Ball for answers")
    @app_commands.describe(question="The question to ask")
    async def slash_8ball(self, interaction: discord.Interaction, question: str) -> None:
        """Slash command version of 8ball."""
        response, color = random.choice(EIGHT_BALL_RESPONSES)
        embed = discord.Embed(color=color)
        embed.set_author(name="🎱 Magic 8-Ball", icon_url=None)
        embed.add_field(name="❓ Question", value=f"*{question}*", inline=False)
        embed.add_field(name="✨ Answer", value=response, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="coinflip", description="Flip a coin to get heads or tails")
    async def slash_coinflip(self, interaction: discord.Interaction) -> None:
        """Slash command version of coinflip."""
        result, emoji, color = random.choice([
            ("Heads", "🪙", 0xF1C40F),
            ("Tails", "🪙", 0x3498DB),
        ])
        embed = self._make_embed("🪙 Coin Flip", color)
        embed.description = f"# {emoji} **{result}!**"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roll", description="Roll dice in NdM format")
    @app_commands.describe(dice="Dice format (e.g. 1d6, 2d20)")
    async def slash_roll(self, interaction: discord.Interaction, dice: str = "1d6") -> None:
        """Slash command version of roll."""
        try:
            n_str, m_str = dice.lower().split("d")
            n, m = int(n_str or 1), int(m_str)
            if not (1 <= n <= 20 and 2 <= m <= 1000):
                raise ValueError
        except ValueError:
            embed = self._make_embed("🎲 Dice Error", 0xE74C3C)
            embed.description = "❌ Invalid format. Use `NdM` (e.g. `2d20`)"
            await interaction.response.send_message(embed=embed)
            return

        rolls = [random.randint(1, m) for _ in range(n)]
        total = sum(rolls)

        embed = self._make_embed("🎲 Dice Roll", 0x2ECC71)
        embed.add_field(name="Roll", value=f"`{dice}`", inline=True)
        embed.add_field(name="Results", value=" + ".join(f"`{r}`" for r in rolls), inline=False)
        embed.add_field(name="**Total**", value=f"# {total}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="joke", description="Get a random programming joke")
    async def slash_joke(self, interaction: discord.Interaction) -> None:
        """Slash command version of joke."""
        url = "https://v2.jokeapi.dev/joke/Programming?blacklistFlags=nsfw,racist,sexist"
        try:
            assert self._session is not None
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
            if data.get("type") == "single":
                text = data["joke"]
            else:
                text = f"{data['setup']}\n\n||{data['delivery']}||"
        except Exception:
            text = "Why do programmers prefer dark mode?\nBecause light attracts bugs!"

        embed = discord.Embed(title="😄 Programming Joke", description=text, color=0xF1C40F)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="fact", description="Learn a random fun fact")
    async def slash_fact(self, interaction: discord.Interaction) -> None:
        """Slash command version of fact."""
        fact = random.choice(FUN_FACTS)
        embed = discord.Embed(color=0x1ABC9C)
        embed.set_author(name="💡 Did You Know?", icon_url=None)
        embed.description = f"**{fact}**"
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Fun(bot))
