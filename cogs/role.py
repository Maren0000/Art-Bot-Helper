from discord.ext import commands
import discord

class RoleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id == 1399828849352773794:
            match payload.emoji.name:
                case "layla_heart":
                    role = discord.utils.get(payload.member.guild.roles, name="Shenhe")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "blackswan_fingerheart":
                    role = discord.utils.get(payload.member.guild.roles, name="Firefly")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "seele_shy":
                    role = discord.utils.get(payload.member.guild.roles, name="Kiana")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "yanagi_yes":
                    role = discord.utils.get(payload.member.guild.roles, name="Yanagi")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "noa_happy":
                    role = discord.utils.get(payload.member.guild.roles, name="Mika")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "amiya_drum":
                    role = discord.utils.get(payload.member.guild.roles, name="Dusk")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "shorekeeper_love":
                    role = discord.utils.get(payload.member.guild.roles, name="Jinshi")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "riceshower_eat":
                    role = discord.utils.get(payload.member.guild.roles, name="Kitasan Black")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "kanade_kira":
                    role = discord.utils.get(payload.member.guild.roles, name="Kanade")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "miku_wave":
                    role = discord.utils.get(payload.member.guild.roles, name="Miku")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "ameliawatson_reading":
                    role = discord.utils.get(payload.member.guild.roles, name="Gura")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "violet_gift":
                    role = discord.utils.get(payload.member.guild.roles, name="Akane")
                    await payload.member.add_roles(role, reason="Reaction Role")
                case "kouzy":
                    role = discord.utils.get(payload.member.guild.roles, name="Hikari")
                    await payload.member.add_roles(role, reason="Reaction Role")
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.message_id == 1399828849352773794:
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            match payload.emoji.name:
                case "layla_heart":
                    role = discord.utils.get(guild.roles, name="Shenhe")
                    await member.remove_roles(role, reason="Reaction Role")
                case "blackswan_fingerheart":
                    role = discord.utils.get(guild.roles, name="Firefly")
                    await member.remove_roles(role, reason="Reaction Role")
                case "seele_shy":
                    role = discord.utils.get(guild.roles, name="Kiana")
                    await member.remove_roles(role, reason="Reaction Role")
                case "yanagi_yes":
                    role = discord.utils.get(guild.roles, name="Yanagi")
                    await member.remove_roles(role, reason="Reaction Role")
                case "noa_happy":
                    role = discord.utils.get(guild.roles, name="Mika")
                    await member.remove_roles(role, reason="Reaction Role")
                case "amiya_drum":
                    role = discord.utils.get(guild.roles, name="Dusk")
                    await member.remove_roles(role, reason="Reaction Role")
                case "shorekeeper_love":
                    role = discord.utils.get(guild.roles, name="Jinshi")
                    await member.remove_roles(role, reason="Reaction Role")
                case "riceshower_eat":
                    role = discord.utils.get(guild.roles, name="Kitasan Black")
                    await member.remove_roles(role, reason="Reaction Role")
                case "kanade_kira":
                    role = discord.utils.get(guild.roles, name="Kanade")
                    await member.remove_roles(role, reason="Reaction Role")
                case "miku_wave":
                    role = discord.utils.get(guild.roles, name="Miku")
                    await member.remove_roles(role, reason="Reaction Role")
                case "ameliawatson_reading":
                    role = discord.utils.get(guild.roles, name="Gura")
                    await member.remove_roles(role, reason="Reaction Role")
                case "violet_gift":
                    role = discord.utils.get(guild.roles, name="Akane")
                    await member.remove_roles(role, reason="Reaction Role")
                case "kouzy":
                    role = discord.utils.get(guild.roles, name="Hikari")
                    await member.remove_roles(role, reason="Reaction Role")

async def setup(bot):
    await bot.add_cog(RoleCog(bot))
