# main.py
import asyncio
import os
import platform
import sys
from datetime import datetime
from io import BytesIO

import google.generativeai as genai
import paramiko
import psutil
import pyodbc
from discord.ext import commands
import discord

from utils import setup_logging, logger, is_admin, split_text
from hosts import load_hosts, save_hosts
from ssh_manager import load_ssh_credentials, save_ssh_credentials, run_ssh_command
from knowledge import save_knowledge, learn_file_to_db, search_knowledge
from ai_prompt import build_prompt
from dotenv import load_dotenv

# load environment
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))

setup_logging()

# configure Gemini model
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ---------- Events ----------
@bot.event
async def on_ready():
    logger.info("Bot ready: %s", bot.user)
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if channel:
        await channel.send("🤖 **NetBot online!**")
    try:
        await bot.tree.sync()
        logger.info("Slash commands synced")
        bot.loop.create_task(monitor_system())
    except Exception:
        logger.exception("Failed to sync commands")

@bot.event
async def on_message(message: discord.Message):
    # ignore self
    if message.author == bot.user:
        return

    # trigger on mention or literal NETBOT word
    if bot.user.mentioned_in(message) or "NETBOT" in message.content.upper():
        await message.channel.send("⏳ Thinking...")
        user_id = message.author.id
        # remove literal "NetBot" (case-insensitive) before question
        question = message.content.replace("NetBot", "").strip()
        try:
            prompt = await build_prompt(user_id, question)
            # run Gemini call in thread
            response = await asyncio.to_thread(lambda: model.generate_content(prompt))
            answer = getattr(response, "text", None) or "⚠️ AI did not answer."
            # save conversation to DB (knowledge.save_to_history inside build_prompt may be used)
            # if long, send as file
            if len(answer) > 1900:
                bio = BytesIO(answer.encode("utf-8"))
                await message.channel.send(file=discord.File(bio, filename="answer.txt"))
            else:
                await message.channel.send(answer)
        except Exception:
            logger.exception("Error handling mention")
            await message.channel.send("❌ Error processing your request.")
    await bot.process_commands(message)

# ---------- Slash commands ----------
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms")

@bot.tree.command(name="addhost", description="Add a nickname for a host (admin only)")
async def addhost(interaction: discord.Interaction, nick: str, ip: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Permission denied", ephemeral=True)
        return
    hosts = load_hosts()
    hosts[nick] = ip
    save_hosts(hosts)
    await interaction.response.send_message(f"✅ Added {nick} -> {ip}", ephemeral=True)

@bot.tree.command(name="listhosts", description="List saved host nicknames")
async def listhosts(interaction: discord.Interaction):
    hosts = load_hosts()
    if not hosts:
        await interaction.response.send_message("No hosts saved", ephemeral=True)
        return
    text = "\n".join(f"{n} → {i}" for n, i in hosts.items())
    if len(text) > 1900:
        bio = BytesIO(text.encode("utf-8"))
        await interaction.response.send_message(file=discord.File(bio, "hosts.txt"), ephemeral=True)
    else:
        await interaction.response.send_message(f"📚 Hosts:\n```{text}```", ephemeral=True)

@bot.tree.command(name="setcred", description="Save SSH credentials for a host (admin only)")
async def setcred(interaction: discord.Interaction, host: str, username: str, password: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Permission denied", ephemeral=True)
        return
    creds = load_ssh_credentials()
    creds[host] = {"username": username, "password": password}
    save_ssh_credentials(creds)
    await interaction.response.send_message(f"✅ Saved credentials for {host}", ephemeral=True)

@bot.tree.command(name="rmcred", description="Remove credentials for a host (admin only)")
async def rmcred(interaction: discord.Interaction, host: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Permission denied", ephemeral=True)
        return
    creds = load_ssh_credentials()
    if host in creds:
        creds.pop(host)
        save_ssh_credentials(creds)
        await interaction.response.send_message(f"✅ Removed credentials for {host}", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Not found", ephemeral=True)

@bot.tree.command(name="ssh", description="Run SSH command on host (username/password optional)")
async def ssh_command(interaction: discord.Interaction, target: str, cmd: str, username: str = None, password: str = None):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Permission denied", ephemeral=True)
        return

    ip_or_nick = target
    # resolve nick -> ip if exists
    hosts = load_hosts()
    ip = hosts.get(ip_or_nick, ip_or_nick) if ip_or_nick else None

    await interaction.response.send_message(f"🔐 Connecting to `{ip}`...", ephemeral=True)
    if not ip:
        await interaction.followup.send("❌ Cannot resolve host", ephemeral=True)
        return

    if not username or not password:
        creds = load_ssh_credentials()
        c = creds.get(ip, {})
        username = username or c.get("username")
        password = password or c.get("password")

    if not (username and password):
        await interaction.followup.send("❌ Missing credentials. Use /setcred or provide username/password.", ephemeral=True)
        return

    result = await asyncio.to_thread(run_ssh_command, ip, username, password, cmd)
    # send result (trim/file if long)
    if isinstance(result, str) and len(result) > 1900:
        bio = BytesIO(result.encode("utf-8"))
        await interaction.followup.send(file=discord.File(bio, f"{ip}_output.txt"))
    else:
        await interaction.followup.send(f"```\n{result}\n```")

@bot.tree.command(name="learn", description="Train bot from a text file (admin only)")
async def learn(interaction: discord.Interaction, filename: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Permission denied", ephemeral=True)
        return
    if not os.path.exists(filename):
        await interaction.response.send_message(f"⚠️ File not found: {filename}", ephemeral=True)
        return
    await interaction.response.send_message(f"⏳ Processing {filename}...", ephemeral=True)
    try:
        count = learn_file_to_db(filename, db_server=DB_SERVER, db_name=DB_NAME)
        await interaction.followup.send(f"✅ Learned {count} chunks from {filename}")
    except Exception:
        logger.exception("learn failed")
        await interaction.followup.send("❌ Error learning file")

@bot.tree.command(name="restart", description="Restart the bot (admin only)")
async def restart_bot(interaction: discord.Interaction):
    if interaction.user.id not in [int(x) for x in os.getenv("ADMIN_USERS", "").split(",") if x]:
        await interaction.response.send_message("🚫 Permission denied", ephemeral=True)
        return
    await interaction.response.send_message("♻️ Restarting...", ephemeral=True)
    await asyncio.sleep(1)
    if platform.system() == "Windows":
        os.execv(sys.executable, ['python'] + sys.argv)
    else:
        os.execv(sys.executable, ['python3'] + sys.argv)

# ---------- Monitoring ----------
async def monitor_system():
    await bot.wait_until_ready()
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        logger.warning("Alert channel not set or not found")
        return
    logger.info("Starting system monitor loop")
    try:
        while not bot.is_closed():
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            alerts = []
            if cpu > 95:
                alerts.append(f"⚠️ CPU high: {cpu}%")
            if ram > 90:
                alerts.append(f"⚠️ RAM high: {ram}%")
            if disk > 90:
                alerts.append(f"⚠️ Disk near full: {disk}%")
            if alerts:
                await channel.send("🚨 **SYSTEM ALERT**\n" + "\n".join(alerts))
            await asyncio.sleep(600)
    except Exception:
        logger.exception("monitor_system loop failed")

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("DISCORD_TOKEN missing in .env")
        raise SystemExit("Missing DISCORD_TOKEN")
    bot.run(BOT_TOKEN)
