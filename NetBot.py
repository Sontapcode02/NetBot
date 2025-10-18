import os
import asyncio
import psutil
import google.generativeai as genai
from dotenv import load_dotenv
from discord.ext import commands
import discord
import pyodbc
import subprocess
import shlex
from datetime import datetime
from io import BytesIO
import platform
# ─── TẢI BIẾN MÔI TRƯỜNG ───────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", 0))
# ─── CẤU HÌNH GEMINI ───────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ─── CẤU HÌNH BOT ─────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ─── PHÂN QUYỀN USER ─────────────────────────────────
ADMIN_USERS = os.getenv("ADMIN_USERS","")
ADMIN_USERS = [int(x.strip()) for x in ADMIN_USERS.split(",") if x.strip()]
def is_admin(user_id: int):
    return int(user_id) in ADMIN_USERS

# ─── KẾT NỐI DATABASE ───────────────────────────────
conn_str = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"Trusted_Connection=yes;"
)
conn = pyodbc.connect(conn_str)
cursor = conn.cursor()

# ─── CÀI ĐẶT MAX TOKENS ─────────────────────────────
MAX_TOKENS = 3000

async def build_prompt(user_id, question, history_limit=50):
    user_history = get_user_history(user_id)
    recent_history = user_history[-history_limit:]

    total_tokens = 0
    filtered_history = []
    for msg in reversed(recent_history):
        tokens = len(msg['content'].split())
        if total_tokens + tokens > MAX_TOKENS:
            break
        filtered_history.insert(0, (msg['role'], msg['content']))
        total_tokens += tokens

    context_text = "\n".join([f"{role.capitalize()}: {content}" for role, content in filtered_history])
    prompt = f"{context_text}\nUser: {question}\nAI:"
    return prompt

# ─── LƯU LỊCH SỬ ───────────────────────────────
def save_to_history(user_id, message, response):
    cursor.execute("""
        INSERT INTO ChatHistory (UserId, Message, Response)
        VALUES (?, ?, ?)
    """, user_id, message, response)
    conn.commit()

def get_user_history(user_id, limit=10):
    cursor.execute("""
        SELECT Message, Response
        FROM ChatHistory
        WHERE UserId=?
        ORDER BY Timestamp DESC
    """, user_id)
    rows = cursor.fetchmany(limit)
    
    history = []
    for row in reversed(rows):
        history.append({"role": "user", "content": row[0]})
        history.append({"role": "assistant", "content": row[1]})
    return history

# ─── HÀM CHIA CHUỖI DÀI ─────────────────────────────
def split_text(text: str, limit: int = 1900):
    chunks = []
    while len(text) > limit:
        idx = text.rfind('\n', 0, limit)
        if idx == -1:
            idx = text.rfind(' ', 0, limit)
        if idx == -1:
            idx = limit
        chunks.append(text[:idx].strip())
        text = text[idx:].strip()
    if text:
        chunks.append(text)
    return chunks

# ─── SỰ KIỆN BOT READY ─────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} đã sẵn sàng!")
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced!")
        
        bot.loop.create_task(monitor_system())
    except Exception as e:
        print(f"❌ Lỗi sync commands: {e}")        
# ─── SLASH COMMANDS ─────────────────────────────
@bot.tree.command(name="ping", description="Kiểm tra độ trễ của bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency*1000)}ms")

@bot.tree.command(name="system", description="Xem thông tin hệ thống chi tiết (Admin Only)")
async def system(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    cpu_total = psutil.cpu_percent()
    cpu_per_core = psutil.cpu_percent(percpu=True)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    os_name = platform.system()
    os_version = platform.version()

    msg = f"""
💻 **Hệ thống:** {os_name} {os_version}
⏱ **Uptime:** {str(uptime).split('.')[0]}

**CPU:** {cpu_total}% tổng
{', '.join([f'Core {i+1}: {v}%' for i, v in enumerate(cpu_per_core)])}

**RAM:** {ram.used/1024**3:.2f}/{ram.total/1024**3:.2f} GB dùng
**Ổ cứng:** {disk.used/1024**3:.2f}/{disk.total/1024**3:.2f} GB dùng
**Còn trống:** {disk.free/1024**3:.2f} GB
"""
    await interaction.response.send_message(msg)
    
@bot.tree.command(name="exec", description="Chạy lệnh hệ thống (Admin Only)")
async def exec_command(interaction: discord.Interaction, command: str):
    # Kiểm tra quyền
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)
        return

    # Thông báo đang chạy
    await interaction.response.send_message(f"⏳ Đang thực thi: `{command}`", ephemeral=True)

    try:
        # Chia command ra list
        args = shlex.split(command)

        # Thực thi lệnh với timeout 10s
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr

        if not output:
            output = "✅ Lệnh chạy thành công nhưng không có output."

        # Nếu output quá dài, gửi file
        if len(output) > 1900:
            bio = BytesIO(output.encode("utf-8"))
            await interaction.followup.send(file=discord.File(bio, filename="output.txt"))
        else:
            await interaction.followup.send(f"```\n{output}\n```")

    except subprocess.TimeoutExpired:
        await interaction.followup.send("❌ Lỗi: Lệnh vượt quá thời gian timeout (10s).")
    except Exception as e:
        await interaction.followup.send(f"❌ Lỗi khi chạy lệnh: {e}")
# ─── XỬ LÝ TIN NHẮN MENTION ─────────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    if "NETBOT" in message.content.upper():
        await message.channel.send("⏳ Đang suy nghĩ...")

        user_id = message.author.id
        question = message.content.replace("NetBot", "").strip()

        try:
            prompt = await build_prompt(user_id, question)
            response = await asyncio.to_thread(lambda: model.generate_content(prompt))
            answer = getattr(response, "text", None) or "⚠️ AI không trả lời."

            save_to_history(user_id, question, answer)

            # Nội dung dài -> gửi file
            if len(answer) > 1900:
                bio = BytesIO(answer.encode('utf-8'))
                await message.channel.send(file=discord.File(bio, filename="answer.txt"))
            else:
                await message.channel.send(answer)

        except Exception as e:
            await message.channel.send(f"❌ Lỗi khi gọi API: {e}")
import asyncio

#------------ Cảnh Báo Tự Động --------------------
async def monitor_system():
    await bot.wait_until_ready()
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        print("⚠️ Không tìm thấy kênh cảnh báo. Kiểm tra ALERT_CHANNEL_ID.")
        return

    print("🔍 Bắt đầu giám sát hệ thống...")

    # Nếu có wmi (chỉ trên Windows)
    try:
        import wmi
        w = wmi.WMI(namespace="root\\wmi")
    except Exception:
        w = None

    while not bot.is_closed():
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent

            # ---- Đọc nhiệt độ CPU ----
            cpu_temp = "N/A"
            if w:
                try:
                    temps = w.MSAcpi_ThermalZoneTemperature()
                    if temps:
                        # Lấy giá trị đầu tiên (nhiệt độ tính bằng Kelvin * 10)
                        cpu_temp = round((temps[0].CurrentTemperature / 10) - 273.15, 1)
                except Exception as e:
                    print(f"Lỗi đọc nhiệt độ CPU (Windows): {e}")
                    cpu_temp = "Không đọc được"

            # ---- Đọc nhiệt độ ổ cứng ----
            hdd_temp = "N/A"
            try:
                if hasattr(psutil, "sensors_temperatures"):
                    temps = psutil.sensors_temperatures()
                    if temps:
                        for name, entries in temps.items():
                            if entries:
                                hdd_temp = round(entries[0].current, 1)
                                break
            except Exception as e:
                print(f"Lỗi đọc nhiệt độ ổ đĩa: {e}")
                hdd_temp = "Không đọc được"

            # ---- Cảnh báo ----
            alerts = []
            if cpu > 85:
                alerts.append(f"⚠️ CPU cao: {cpu}%")
            if ram > 85:
                alerts.append(f"⚠️ RAM sử dụng cao: {ram}%")
            if disk > 90:
                alerts.append(f"⚠️ Ổ đĩa gần đầy: {disk}%")

            # ---- Thêm cảnh báo nhiệt độ ----
            if isinstance(cpu_temp, (int, float)) and cpu_temp > 80:
                alerts.append(f"🔥 Nhiệt độ CPU cao: {cpu_temp}°C")
            if isinstance(hdd_temp, (int, float)) and hdd_temp > 60:
                alerts.append(f"🔥 Ổ đĩa nóng: {hdd_temp}°C")

            if alerts:
                msg = "\n".join(alerts)
                await channel.send(f"🚨 **CẢNH BÁO HỆ THỐNG!**\n{msg}")

            await asyncio.sleep(600)

        except Exception as e:
            print(f"❌ Lỗi trong giám sát: {e}")
            await asyncio.sleep(600)
# ─── CHẠY BOT ─────────────────────────────
if BOT_TOKEN:
    bot.run(BOT_TOKEN)
else:
    print("❌ Không tìm thấy DISCORD_TOKEN trong .env")
