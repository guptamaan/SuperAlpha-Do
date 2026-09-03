"""
cogs/games.py — Interactive games commands.
Commands: tictactoe, connect4, wordbank
"""

import asyncio
import random

import discord
from discord.ext import commands


class TicTacToe:
    def __init__(self, p1: discord.User, p2: discord.User) -> None:
        self.board = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]]
        self.players = {p1: "❌", p2: "⭕"}
        self.current = p1
        self.p1 = p1
        self.p2 = p2
        self.game_over = False
        self.winner = None

    def render(self) -> str:
        board = self.board
        return (
            f"```\n"
            f" {board[0][0]} │ {board[0][1]} │ {board[0][2]} \n"
            f"───┼───┼───\n"
            f" {board[1][0]} │ {board[1][1]} │ {board[1][2]} \n"
            f"───┼───┼───\n"
            f" {board[2][0]} │ {board[2][1]} │ {board[2][2]} \n"
            f"```"
        )

    def check_win(self, symbol: str) -> bool:
        b = self.board
        for i in range(3):
            if b[i][0] == b[i][1] == b[i][2] == symbol:
                return True
            if b[0][i] == b[1][i] == b[2][i] == symbol:
                return True
        if b[0][0] == b[1][1] == b[2][2] == symbol:
            return True
        if b[0][2] == b[1][1] == b[2][0] == symbol:
            return True
        return False

    def check_draw(self) -> bool:
        return all(cell in ("❌", "⭕") for row in self.board for cell in row)

    def move(self, pos: int, user: discord.User) -> str:
        if user != self.current:
            return "❌ Not your turn!"
        if not 1 <= pos <= 9:
            return "❌ Invalid position!"

        row, col = (pos - 1) // 3, (pos - 1) % 3
        if self.board[row][col] in ("❌", "⭕"):
            return "❌ Position already taken!"

        symbol = self.players[user]
        self.board[row][col] = symbol

        if self.check_win(symbol):
            self.game_over = True
            self.winner = user
            return f"🏆 {user.mention} wins!"
        if self.check_draw():
            self.game_over = True
            return "🤝 It's a draw!"
        
        self.current = self.p2 if self.current == self.p1 else self.p1
        return ""


class Connect4:
    def __init__(self, p1: discord.User, p2: discord.User) -> None:
        self.board = [["⚪" for _ in range(7)] for _ in range(6)]
        self.players = {p1: "🔴", p2: "🟡"}
        self.current = p1
        self.p1 = p1
        self.p2 = p2
        self.game_over = False
        self.winner = None

    def render(self) -> str:
        nums = "1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣"
        rows = [" ".join(row) for row in self.board]
        return f"```\n{nums}\n" + "\n".join(rows) + "\n```"

    def check_win(self, symbol: str) -> bool:
        for row in range(6):
            for col in range(7):
                if self._check_direction(row, col, symbol, 0, 1):
                    return True
                if self._check_direction(row, col, symbol, 1, 0):
                    return True
                if self._check_direction(row, col, symbol, 1, 1):
                    return True
                if self._check_direction(row, col, symbol, 1, -1):
                    return True
        return False

    def _check_direction(self, row: int, col: int, symbol: str, dr: int, dc: int) -> bool:
        for i in range(4):
            r, c = row + dr * i, col + dc * i
            if r < 0 or r >= 6 or c < 0 or c >= 7:
                return False
            if self.board[r][c] != symbol:
                return False
        return True

    def move(self, col: int, user: discord.User) -> str:
        if user != self.current:
            return "❌ Not your turn!"
        if not 1 <= col <= 7:
            return "❌ Invalid column! Choose 1-7"
        
        col -= 1
        for row in range(5, -1, -1):
            if self.board[row][col] == "⚪":
                self.board[row][col] = self.players[user]
                if self.check_win(self.players[user]):
                    self.game_over = True
                    self.winner = user
                    return f"🏆 {user.mention} wins!"
                if all(cell != "⚪" for row in self.board for cell in row):
                    self.game_over = True
                    return "🤝 It's a draw!"
                self.current = self.p2 if self.current == self.p1 else self.p1
                return ""
        return "❌ Column is full!"


class WordBank:
    WORDS = [
        "python", "discord", "programming", "computer", "algorithm",
        "variable", "function", "database", "network", "server",
        "keyboard", "monitor", "developer", "software", "hardware",
        "application", "interface", "framework", "library", "terminal",
    ]

    def __init__(self) -> None:
        self.word = random.choice(self.WORDS)
        self.display = ["_"] * len(self.word)
        self.guessed: set[str] = set()
        self.max_wrong = 6
        self.wrong = 0
        self.game_over = False
        self.won = False

    def guess(self, letter: str) -> str:
        if self.game_over:
            return "Game already over!"

        letter = letter.lower()
        if len(letter) != 1 or not letter.isalpha():
            return "❌ Guess a single letter!"

        if letter in self.guessed:
            return f"❌ '{letter}' already guessed!"

        self.guessed.add(letter)

        if letter in self.word:
            for i, c in enumerate(self.word):
                if c == letter:
                    self.display[i] = letter
            if "_" not in self.display:
                self.game_over = True
                self.won = True
                return f"🏆 You win! The word was **{self.word}**"
            return f"✅ Found '{letter}'!"
        else:
            self.wrong += 1
            if self.wrong >= self.max_wrong:
                self.game_over = True
                return f"💀 Game over! The word was **{self.word}**"
            return f"❌ Wrong! {self.max_wrong - self.wrong} guesses left"


class Games(commands.Cog, name="games"):
    """Interactive games commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.ttt_games: dict[int, TicTacToe] = {}
        self.c4_games: dict[int, Connect4] = {}
        self.wb_games: dict[int, WordBank] = {}
        self.ttt_messages: dict[int, discord.Message] = {}
        self.c4_messages: dict[int, discord.Message] = {}

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    # ── Tic-Tac-Toe ───────────────────────────────────────────────────────────
    @commands.command(name="tictactoe", aliases=["ttt", "xox"])
    @commands.cooldown(1, 20, commands.BucketType.channel)
    async def tictactoe(self, ctx: commands.Context, opponent: discord.User) -> None:
        """Play Tic-Tac-Toe with someone. Usage: sudo tictactoe @user"""
        if opponent.bot:
            embed = self._make_embed("❌ Invalid Opponent", 0xE74C3C, "Bots cannot play!")
            await ctx.send(embed=embed)
            return
        if opponent == ctx.author:
            embed = self._make_embed("❌ Invalid", 0xE74C3C, "You cannot play against yourself!")
            await ctx.send(embed=embed)
            return

        game = TicTacToe(ctx.author, opponent)
        self.ttt_games[ctx.channel.id] = game

        embed = discord.Embed(
            title="❌⭕ Tic-Tac-Toe",
            description=f"{ctx.author.mention} vs {opponent.mention}\n\n{game.render()}\n\n**{ctx.author.mention}'s turn** (❌)\nPick a number 1-9 to place your mark.",
            color=0x3498DB,
        )
        embed.set_footer(text="Type a number to play | Game ID: " + str(ctx.channel.id))
        msg = await ctx.send(embed=embed)
        self.ttt_messages[ctx.channel.id] = msg

        try:
            while not game.game_over:
                def check(m):
                    return m.author == game.current and m.channel == ctx.channel and m.content.isdigit() and 1 <= int(m.content) <= 9

                move_msg = await self.bot.wait_for("message", timeout=60.0, check=check)
                pos = int(move_msg.content)
                result = game.move(pos, move_msg.author)

                if result and ("wins" in result or "draw" in result):
                    embed = discord.Embed(
                        title="❌⭕ Game Over",
                        description=f"{game.render()}\n\n{result}",
                        color=0x2ECC71 if "wins" in result else 0xF39C12,
                    )
                    await move_msg.delete()
                    await self.ttt_messages[ctx.channel.id].edit(embed=embed)
                    break

                if result and ("Invalid" in result or "taken" in result):
                    await move_msg.delete()
                    await ctx.send(result, delete_after=2)
                    continue

                await move_msg.delete()
                new_embed = discord.Embed(
                    title="❌⭕ Tic-Tac-Toe",
                    description=f"{game.render()}\n\n**{game.current.mention}'s turn** ({game.players[game.current]})",
                    color=0x3498DB,
                )
                new_embed.set_footer(text="Type a number to play")
                await self.ttt_messages[ctx.channel.id].edit(embed=new_embed)

        except asyncio.TimeoutError:
            embed = self._make_embed("⏰ Time's Up!", 0x95A5A6, f"{game.current.mention} took too long to move.")
            await self.ttt_messages[ctx.channel.id].edit(embed=embed)

        finally:
            self.ttt_games.pop(ctx.channel.id, None)
            self.ttt_messages.pop(ctx.channel.id, None)

    # ── Connect 4 ────────────────────────────────────────────────────────────
    @commands.command(name="connect4", aliases=["c4", "four"])
    @commands.cooldown(1, 20, commands.BucketType.channel)
    async def connect4(self, ctx: commands.Context, opponent: discord.User) -> None:
        """Play Connect 4 with someone. Usage: sudo connect4 @user"""
        if opponent.bot:
            embed = self._make_embed("❌ Invalid Opponent", 0xE74C3C, "Bots cannot play!")
            await ctx.send(embed=embed)
            return
        if opponent == ctx.author:
            embed = self._make_embed("❌ Invalid", 0xE74C3C, "You cannot play against yourself!")
            await ctx.send(embed=embed)
            return

        game = Connect4(ctx.author, opponent)
        self.c4_games[ctx.channel.id] = game

        embed = discord.Embed(
            title="🔴🟡 Connect 4",
            description=f"{ctx.author.mention} vs {opponent.mention}\n\n{game.render()}\n\n**{ctx.author.mention}'s turn** (🔴)\nChoose a column 1-7.",
            color=0x3498DB,
        )
        embed.set_footer(text="Type a number 1-7 to play")
        msg = await ctx.send(embed=embed)
        self.c4_messages[ctx.channel.id] = msg

        try:
            while not game.game_over:
                def check(m):
                    return m.author == game.current and m.channel == ctx.channel and m.content.isdigit() and 1 <= int(m.content) <= 7

                move_msg = await self.bot.wait_for("message", timeout=60.0, check=check)
                col = int(move_msg.content)
                result = game.move(col, move_msg.author)

                if result and ("wins" in result or "draw" in result):
                    embed = discord.Embed(
                        title="🔴🟡 Game Over",
                        description=f"{game.render()}\n\n{result}",
                        color=0x2ECC71 if "wins" in result else 0xF39C12,
                    )
                    await move_msg.delete()
                    await self.c4_messages[ctx.channel.id].edit(embed=embed)
                    break

                if result and ("Invalid" in result or "full" in result):
                    await move_msg.delete()
                    await ctx.send(result, delete_after=2)
                    continue

                await move_msg.delete()
                new_embed = discord.Embed(
                    title="🔴🟡 Connect 4",
                    description=f"{game.render()}\n\n**{game.current.mention}'s turn** ({game.players[game.current]})",
                    color=0x3498DB,
                )
                new_embed.set_footer(text="Type a number 1-7 to play")
                await self.c4_messages[ctx.channel.id].edit(embed=new_embed)

        except asyncio.TimeoutError:
            embed = self._make_embed("⏰ Time's Up!", 0x95A5A6, f"{game.current.mention} took too long to move.")
            await self.c4_messages[ctx.channel.id].edit(embed=embed)

        finally:
            self.c4_games.pop(ctx.channel.id, None)
            self.c4_messages.pop(ctx.channel.id, None)

    # ── Word Bank ─────────────────────────────────────────────────────────────
    @commands.command(name="wordbank", aliases=["hangman", "wb"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def wordbank(self, ctx: commands.Context) -> None:
        """Play a word guessing game. Usage: sudo wordbank"""
        game = WordBank()
        self.wb_games[ctx.author.id] = game

        embed = discord.Embed(
            title="🔤 Word Bank",
            description=f"Guess the word! You have **{game.max_wrong}** wrong guesses allowed.\n\n`" + " ".join(game.display) + "`\n\nGuessed letters: none",
            color=0x9B59B6,
        )
        embed.set_footer(text="Type a single letter to guess | End game with 'end'")
        await ctx.send(embed=embed)

        try:
            while not game.game_over:
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel

                guess_msg = await self.bot.wait_for("message", timeout=120.0, check=check)
                guess = guess_msg.content.lower()

                if guess == "end":
                    embed = self._make_embed("🏁 Game Ended", 0x95A5A6, f"The word was **{game.word}**")
                    await ctx.send(embed=embed)
                    break

                result = game.guess(guess)
                guessed_str = ", ".join(sorted(game.guessed)) if game.guessed else "none"

                if "wins" in result or "over" in result:
                    embed = discord.Embed(
                        title="🔤 Word Bank",
                        description=f"`{' '.join(game.display)}`\n\n{result}\n\nGuessed: {guessed_str}",
                        color=0x2ECC71 if game.won else 0xE74C3C,
                    )
                    await ctx.send(embed=embed)
                    break

                embed = discord.Embed(
                    title="🔤 Word Bank",
                    description=f"`{' '.join(game.display)}`\n\n{result}\n\nGuessed letters: {guessed_str}",
                    color=0x9B59B6,
                )
                embed.set_footer(text="Type a single letter to guess | End game with 'end'")
                await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            embed = self._make_embed("⏰ Time's Up!", 0x95A5A6, f"The word was **{game.word}**")
            await ctx.send(embed=embed)

        finally:
            self.wb_games.pop(ctx.author.id, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Games(bot))
