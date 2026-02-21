import discord
from discord.ext import commands, tasks
import sqlite3
import random
import os
import requests
from datetime import datetime

# --- CẤU HÌNH BIẾN (LẤY TỪ RAILWAY) ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')

# QUAN TRỌNG: Bạn hãy thay ID kênh thật của bạn vào 2 dòng dưới đây
ID_KENH_BONG_DA = 1474672512708247582  # Chuột phải vào kênh cược -> Copy ID
ID_KENH_BXH = 1474674662792232981      # Chuột phải vào kênh BXH -> Copy ID

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

DB_PATH = '/app/economy.db'

def update_db(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    # Khởi tạo database
    update_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    # Chạy các tác vụ lặp lại
    auto_upcoming_matches.start()
    auto_update_bxh.start()
    print(f'✅ Bot {bot.user} đã sẵn sàng và đang lấy dữ liệu bóng đá!')

# --- 🏆 BẢNG XẾP HẠNG TỰ ĐỘNG ---
@tasks.loop(minutes=30)
async def auto_update_bxh():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    conn = sqlite3.connect(DB_PATH)
    users = conn.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10").fetchall()
    conn.close()
    
    embed = discord.Embed(title="🏆 TOP 10 ĐẠI GIA SERVER", color=0xffd700, timestamp=datetime.utcnow())
    for i, (u_id, coins) in enumerate(users, 1):
        member = bot.get_user(u_id)
        name = member.name if member else f"ID: {u_id}"
        embed.add_field(name=f"Top {i}: {name}", value=f"💰 `{coins:,}` Coins", inline=False)
    
    await channel.purge(limit=1)
    await channel.send(embed=embed)

# --- ⚽ HIỂN THỊ KÈO BÓNG ĐÁ (DÙNG FOOTBALL-DATA.ORG) ---
@tasks.loop(minutes=15)
async def auto_upcoming_matches():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    # Lấy trận đấu của giải Ngoại hạng Anh (PL)
    url = "https://api.football-data.org/v4/competitions/PL/matches?status=SCHEDULED"
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        response = requests.get(url, headers=headers).json()
        matches = response.get('matches', [])
        await channel.purge(limit=5)
        
        embed = discord.Embed(title="⚽ KÈO BÓNG ĐÁ NGOẠI HẠNG ANH", color=0x2ecc71, timestamp=datetime.utcnow())
        embed.set_footer(text="Cập nhật tự động sau 15 phút")

        if not matches:
            embed.description = "Hiện chưa có lịch thi đấu mới sắp diễn ra."
        else:
            for m in matches[:8]:
                home = m['homeTeam']['name']
                away = m['awayTeam']['name']
                m_id = m['id']
                # Cắt chuỗi thời gian cho dễ nhìn
                time_str = m['utcDate'][11:16] + " (UTC)"

                embed.add_field(
                    name=f"🆔 ID: {m_id} | ⏱ {time_str}",
                    value=f"🏟 **{home}** vs **{away}**\n🟢 Trạng thái: `Đang nhận cược` ",
                    inline=False
                )
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Lỗi API: {e}")

# --- 🎲 LỆNH TÀI XỈU ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']: return await ctx.send("Dùng: `!taixiu tai 100` hoặc `!taixiu xiu 100`")
    
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,)).fetchone()
    balance = res[0] if res else 0
    
    if balance < cuoc or cuoc < 100:
        return await ctx.send("❌ Bạn không đủ tiền hoặc mức cược tối thiểu là 100!")

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    kq = "tai" if tong >= 11 else "xiu"
    win = (lua_chon == kq)
    
    new_bal = balance + cuoc if win else balance - cuoc
    update_db("INSERT OR REPLACE INTO users (user_id, coins) VALUES (?, ?)", (ctx.author.id, new_bal))

    embed = discord.Embed(title="🎲 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if win else 0xe74c3c)
    embed.add_field(name="Xúc xắc", value=f"🎲 `{dices[0]}-{dices[1]}-{dices[2]}` = **{tong}**", inline=True)
    embed.add_field(name="Kết quả", value=f"✨ **{kq.upper()}**", inline=True)
    embed.add_field(name="Tiền hiện có", value=f"💰 `{new_bal:,}`", inline=False)
    await ctx.send(embed=embed)

# --- 💳 KIỂM TRA VÍ ---
@bot.command()
async def vi(ctx):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,)).fetchone()
    conn.close()
    coins = res[0] if res else 0
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{coins:,} Coins**")

# --- 💸 ADMIN NẠP TIỀN ---
@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    update_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    update_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
    await ctx.send(f"✅ Đã nạp `{amount:,}` cho {member.mention}")

bot.run(TOKEN)
