import discord
from discord.ext import commands, tasks
import sqlite3
import random
import os
import requests
import asyncio

# --- CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
CHANNEL_BONG_DA_ID = 1234567890  # THAY ID KÊNH HIỂN THỊ TỈ SỐ VÀO ĐÂY

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

DB_PATH = '/app/economy.db'

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    # Bảng lưu đơn cược
    c.execute('''CREATE TABLE IF NOT EXISTS bets_bongda 
                 (id INTEGER PRIMARY KEY, user_id INTEGER, match_id INTEGER, 
                  team_bet TEXT, amount INTEGER, handicap REAL, status TEXT DEFAULT 'pending')''')
    conn.commit()
    conn.close()

def update_coins(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (user_id,))
    conn.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    init_db()
    auto_update_bongda.start() # Chạy vòng lặp cập nhật tự động
    print(f'✅ {bot.user} đã sẵn sàng!')

# --- VÒNG LẶP TỰ ĐỘNG CẬP NHẬT TỈ SỐ & TRẢ THƯỞNG ---
@tasks.loop(minutes=5)
async def auto_update_bongda():
    channel = bot.get_channel(CHANNEL_BONG_DA_ID)
    if not channel or not API_KEY: return

    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
    
    try:
        data = requests.get(url, headers=headers).json()
        matches = data.get('response', [])
        
        await channel.purge(limit=5) # Xóa tin nhắn cũ để bảng luôn mới
        
        embed = discord.Embed(title="⚽ BẢNG KÈO BÓNG ĐÁ TRỰC TIẾP", color=0x2ecc71)
        
        for m in matches[:10]:
            m_id = m['fixture']['id']
            home = m['teams']['home']['name']
            away = m['teams']['away']['name']
            h_goal = m['goals']['home']
            a_goal = m['goals']['away']
            
            # GIẢ LẬP KÈO CHẤP (Bot tự tính ngẫu nhiên hoặc theo ID để cố định)
            # Trong thực tế bạn có thể lấy từ Rank, ở đây bot tự tạo kèo 0.5, 1.0 hoặc 1.5
            handicap = random.choice([0.5, 0.75, 1.0, 1.25])
            
            embed.add_field(
                name=f"🆔 ID: {m_id} | ⏱ {m['fixture']['status']['elapsed']}'",
                value=f"🏟 **{home}** (Chấp {handicap}) vs **{away}**\n Tỉ số: `{h_goal} - {a_goal}`",
                inline=False
            )
            
            # TỰ ĐỘNG TRẢ THƯỞNG NẾU TRẬN ĐẤU KẾT THÚC (Nếu bạn check Fixtures status là 'FT')
            # Lưu ý: Phần này cần quét thêm API Fixture Results để tối ưu hơn.

        embed.set_footer(text="Cú pháp cược: !cuoc [ID] [Tên_Đội] [Tiền]")
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Lỗi update: {e}")

# --- LỆNH ĐẶT CƯỢC ---
@bot.command()
async def cuoc(ctx, match_id: int, team: str, amount: int):
    conn = sqlite3.connect(DB_PATH)
    user_coins = conn.execute("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,)).fetchone()
    conn.close()
    
    if not user_coins or user_coins[0] < amount:
        return await ctx.send("❌ Bạn không đủ tiền!")

    # Lưu vào database cược
    # Handicap lấy mặc định 0.5 cho đơn giản trong bản demo này
    handicap = 0.5 
    update_coins(ctx.author.id, -amount)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO bets_bongda (user_id, match_id, team_bet, amount, handicap) VALUES (?, ?, ?, ?, ?)",
                 (ctx.author.id, match_id, team, amount, handicap))
    conn.commit()
    conn.close()
    
    await ctx.send(f"✅ Đã đặt `{amount:,}` Coins vào đội **{team}** (ID: {match_id}, Chấp: {handicap})")

# --- TÀI XỈU & VÍ (NHƯ CŨ) ---
@bot.command()
async def vi(ctx):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,)).fetchone()
    conn.close()
    coins = res[0] if res else 0
    await ctx.send(f"💰 Ví của {ctx.author.mention}: **{coins:,} Coins**")

bot.run(TOKEN)
