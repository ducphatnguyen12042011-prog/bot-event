import discord
from discord.ext import commands, tasks
import os
import requests
from datetime import datetime

# --- LẤY TOKEN TỪ RAILWAY ---
# Biến này để chạy Bot Discord
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN') 
# Biến này để lấy dữ liệu bóng đá
FOOTBALL_KEY = os.getenv('FOOTBALL_API_KEY') 

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Kết nối Discord thành công: {bot.user}')
    check_football.start()

@tasks.loop(minutes=30)
async def check_football():
    if not FOOTBALL_KEY:
        print("❌ Thiếu FOOTBALL_API_KEY trong Variables!")
        return
    
    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": FOOTBALL_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print("⚽ Đã lấy dữ liệu bóng đá thành công!")
        else:
            print(f"⚠️ Lỗi API Bóng đá: {response.status_code}")
    except Exception as e:
        print(f"❌ Lỗi kết nối: {e}")

# Dòng quan trọng nhất: Dùng DISCORD_TOKEN để khởi động
bot.run(DISCORD_TOKEN)
