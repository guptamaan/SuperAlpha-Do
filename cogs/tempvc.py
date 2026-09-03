"""
cogs/tempvc.py — Temporary voice channels.
Creates private VCs on demand with owner controls.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands


class TempVC:
    def __init__(self, channel_id: int, owner_id: int, name: str) -> None:
        self.channel_id: int = channel_id
        self.owner_id: int = owner_id
        self.name: str = name
        self.user_limit: int | None = None
        self.locked: bool = False


class TempVCManager(commands.Cog, name="tempvc"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._vcs: dict[int, TempVC] = {}

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    def _get_vc(self, channel_id: int) -> TempVC | None:
        for vc in self._vcs.values():
            if vc.channel_id == channel_id:
                return vc
        return None

    def _is_owner(self, vc: TempVC, user_id: int) -> bool:
        return vc.owner_id == user_id

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        if before.channel and before.channel != after.channel:
            vc = self._get_vc(before.channel.id)
            if vc:
                try:
                    await asyncio.sleep(0.5)
                    channel = member.guild.get_channel(before.channel.id)
                    if channel and len(channel.members) == 0:
                        try:
                            await channel.delete()
                        except discord.NotFound:
                            pass
                        if vc.channel_id in self._vcs:
                            del self._vcs[vc.channel_id]
                except Exception:
                    pass

    @commands.command(name="createvc", aliases=["makvc", "makevc"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def createvc(self, ctx: commands.Context, *, name: str = "My VC") -> None:
        """Create a temporary voice channel. Usage: sudo createvc [name]"""
        if not ctx.author.voice:
            embed = self._make_embed("❌ Not in VC", 0xE74C3C, "Join a voice channel first")
            await ctx.send(embed=embed)
            return

        category = ctx.author.voice.channel.category
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
            ctx.author: discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True),
        }

        try:
            vc_channel = await category.create_voice_channel(
                name=name[:50],
                user_limit=None,
                overwrites=overwrites,
            )
        except Exception as e:
            embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not create channel: {e}")
            await ctx.send(embed=embed)
            return

        self._vcs[vc_channel.id] = TempVC(vc_channel.id, ctx.author.id, name[:50])

        try:
            await ctx.author.move_to(vc_channel)
        except Exception:
            pass

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="🔊 VC Created")
        embed.description = f"**{name[:50]}** created!"
        embed.add_field(name="Owner", value=ctx.author.mention, inline=True)
        embed.add_field(name="Commands", value="`sudo vc name` `sudo vc limit`\n`sudo vc lock` `sudo vc kick`\n`sudo vc delete`", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="vc", aliases=["tempvc", "voice"])
    async def vc(self, ctx: commands.Context, action: str = None, *, value: str = None) -> None:
        """Manage your temp VC. Usage: sudo vc [name|limit|lock|unlock|kick|delete] [value]"""
        if not ctx.author.voice:
            embed = self._make_embed("❌ Not in VC", 0xE74C3C, "Join a voice channel first")
            await ctx.send(embed=embed)
            return

        channel = ctx.author.voice.channel
        vc = self._get_vc(channel.id)

        if not action:
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name=f"🔊 {channel.name}")
            embed.add_field(name="Owner", value=f"<@{vc.owner_id}>" if vc else "Unknown", inline=True)
            embed.add_field(name="Members", value=f"{len(channel.members)}", inline=True)
            embed.add_field(name="Limit", value=f"{vc.user_limit or 'None'}", inline=True)
            embed.add_field(name="Status", value="🔒 Locked" if (vc and vc.locked) else "🔓 Open", inline=True)
            if vc and self._is_owner(vc, ctx.author.id):
                embed.add_field(name="Commands", value="`sudo vc name <name>`\n`sudo vc limit <0-99>`\n`sudo vc lock/unlock`\n`sudo vc kick @user`\n`sudo vc delete`", inline=False)
            await ctx.send(embed=embed)
            return

        if vc and not self._is_owner(vc, ctx.author.id):
            embed = self._make_embed("❌ Not Owner", 0xE74C3C, "Only the VC owner can do this")
            await ctx.send(embed=embed)
            return

        action = action.lower()

        if action == "name":
            if not value:
                embed = self._make_embed("❌ No Name", 0xE74C3C, "Usage: `sudo vc name <new name>`")
                await ctx.send(embed=embed)
                return
            new_name = value.strip()
            try:
                await channel.edit(name=new_name[:100])
                if vc:
                    vc.name = new_name[:100]
                embed = self._make_embed("✏️ Renamed", 0x2ECC71, f"Channel renamed to **{new_name[:50]}**")
            except Exception as e:
                embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not rename: {e}")
            await ctx.send(embed=embed)

        elif action == "limit":
            if not value or not value.isdigit():
                embed = self._make_embed("❌ Invalid", 0xE74C3C, "Usage: `sudo vc limit <0-99>` (0 = no limit)")
                await ctx.send(embed=embed)
                return
            limit = int(value)
            if limit > 99:
                limit = 99
            try:
                await channel.edit(user_limit=limit if limit > 0 else None)
                if vc:
                    vc.user_limit = limit if limit > 0 else None
                limit_text = f"**{limit}**" if limit > 0 else "**None**"
                embed = self._make_embed("👥 Limit Set", 0x3498DB, f"User limit set to {limit_text}")
            except Exception as e:
                embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not set limit: {e}")
            await ctx.send(embed=embed)

        elif action == "lock":
            try:
                await channel.set_permissions(ctx.guild.default_role, connect=False)
                if vc:
                    vc.locked = True
                embed = self._make_embed("🔒 Locked", 0xE74C3C, "Voice channel is now locked")
            except Exception as e:
                embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not lock: {e}")
            await ctx.send(embed=embed)

        elif action == "unlock":
            try:
                await channel.set_permissions(ctx.guild.default_role, connect=True)
                if vc:
                    vc.locked = False
                embed = self._make_embed("🔓 Unlocked", 0x2ECC71, "Voice channel is now open")
            except Exception as e:
                embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not unlock: {e}")
            await ctx.send(embed=embed)

        elif action == "kick":
            if not value:
                embed = self._make_embed("❌ No User", 0xE74C3C, "Mention a user to kick: `sudo vc kick @user`")
                await ctx.send(embed=embed)
                return
            try:
                kick_id = int(value.replace("<@", "").replace(">", "").replace("!", ""))
                member = ctx.guild.get_member(kick_id)
                if not member or not member.voice or member.voice.channel.id != channel.id:
                    embed = self._make_embed("❌ Not Found", 0xE74C3C, "User not in this voice channel")
                    await ctx.send(embed=embed)
                    return
                await member.move_to(None)
                embed = self._make_embed("👢 Kicked", 0xF39C12, f"**{member.display_name}** was kicked from the channel")
            except Exception as e:
                embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not kick: {e}")
            await ctx.send(embed=embed)

        elif action == "delete":
            if not vc:
                embed = self._make_embed("❌ Not a Temp VC", 0xE74C3C, "This isn't a temporary voice channel")
                await ctx.send(embed=embed)
                return
            try:
                if channel.id in self._vcs:
                    del self._vcs[channel.id]
                await channel.delete()
                embed = self._make_embed("🗑️ Deleted", 0x95A5A6, "Voice channel deleted")
            except Exception as e:
                embed = self._make_embed("❌ Error", 0xE74C3C, f"Could not delete: {e}")
            await ctx.send(embed=embed)

        elif action == "claim":
            if vc:
                embed = self._make_embed("❌ Already Owned", 0xE74C3C, "This channel already has an owner")
                await ctx.send(embed=embed)
                return
            if len(channel.members) > 1:
                embed = self._make_embed("❌ Not Empty", 0xE74C3C, "Channel must be empty to claim")
                await ctx.send(embed=embed)
                return
            self._vcs[channel.id] = TempVC(channel.id, ctx.author.id, channel.name)
            embed = self._make_embed("✅ Claimed", 0x2ECC71, f"**{ctx.author.display_name}** is now the owner")
            await ctx.send(embed=embed)

        elif action == "invite":
            if not value:
                embed = self._make_embed("❌ No User", 0xE74C3C, "Mention a user to invite: `sudo vc invite @user`")
                await ctx.send(embed=embed)
                return
            try:
                invite_id = int(value.replace("<@", "").replace(">", "").replace("!", ""))
                member = ctx.guild.get_member(invite_id)
                if not member:
                    embed = self._make_embed("❌ Not Found", 0xE74C3C, "User not found")
                    await ctx.send(embed=embed)
                    return
                try:
                    await channel.set_permissions(member, connect=True, view_channel=True)
                    embed = self._make_embed("📨 Invited", 0x2ECC71, f"**{member.display_name}** can now join {channel.name}")
                except Exception:
                    embed = self._make_embed("❌ Error", 0xE74C3C, "Could not invite user")
            except Exception:
                embed = self._make_embed("❌ Error", 0xE74C3C, "Invalid user mention")
            await ctx.send(embed=embed)

        elif action == "ban":
            if not value:
                embed = self._make_embed("❌ No User", 0xE74C3C, "Mention a user to ban: `sudo vc ban @user`")
                await ctx.send(embed=embed)
                return
            try:
                ban_id = int(value.replace("<@", "").replace(">", "").replace("!", ""))
                member = ctx.guild.get_member(ban_id)
                if not member:
                    embed = self._make_embed("❌ Not Found", 0xE74C3C, "User not found")
                    await ctx.send(embed=embed)
                    return
                try:
                    await channel.set_permissions(member, connect=False, view_channel=False)
                    if member.voice and member.voice.channel.id == channel.id:
                        await member.move_to(None)
                    embed = self._make_embed("🚫 Banned", 0xE74C3C, f"**{member.display_name}** is banned from this channel")
                except Exception:
                    embed = self._make_embed("❌ Error", 0xE74C3C, "Could not ban user")
            except Exception:
                embed = self._make_embed("❌ Error", 0xE74C3C, "Invalid user mention")
            await ctx.send(embed=embed)

        elif action == "unban":
            if not value:
                embed = self._make_embed("❌ No User", 0xE74C3C, "Mention a user to unban: `sudo vc unban @user`")
                await ctx.send(embed=embed)
                return
            try:
                unban_id = int(value.replace("<@", "").replace(">", "").replace("!", ""))
                member = ctx.guild.get_member(unban_id)
                if not member:
                    embed = self._make_embed("❌ Not Found", 0xE74C3C, "User not found")
                    await ctx.send(embed=embed)
                    return
                try:
                    await channel.set_permissions(member, connect=None, view_channel=None)
                    embed = self._make_embed("✅ Unbanned", 0x2ECC71, f"**{member.display_name}** can now join this channel")
                except Exception:
                    embed = self._make_embed("❌ Error", 0xE74C3C, "Could not unban user")
            except Exception:
                embed = self._make_embed("❌ Error", 0xE74C3C, "Invalid user mention")
            await ctx.send(embed=embed)

        else:
            embed = self._make_embed("❌ Invalid Action", 0xE74C3C, "Valid actions: name, limit, lock, unlock, kick, delete, claim, invite, ban, unban")
            await ctx.send(embed=embed)

    @app_commands.command(name="createvc", description="Create a temporary voice channel")
    @app_commands.describe(name="Channel name (optional)")
    async def slash_createvc(self, interaction: discord.Interaction, name: str = "My VC") -> None:
        if not interaction.user.voice:
            await interaction.response.send_message(embed=self._make_embed("❌ Not in VC", 0xE74C3C, "Join a voice channel first"), ephemeral=True)
            return

        category = interaction.user.voice.channel.category
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
            interaction.user: discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True),
        }

        try:
            vc_channel = await category.create_voice_channel(name=name[:50], user_limit=None, overwrites=overwrites)
        except Exception as e:
            await interaction.response.send_message(embed=self._make_embed("❌ Error", 0xE74C3C, f"Could not create channel: {e}"), ephemeral=True)
            return

        self._vcs[vc_channel.id] = TempVC(vc_channel.id, interaction.user.id, name[:50])

        try:
            await interaction.user.move_to(vc_channel)
        except Exception:
            pass

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="🔊 VC Created")
        embed.description = f"**{name[:50]}** created!"
        embed.add_field(name="Owner", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVCManager(bot))
