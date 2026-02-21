import discord
from discord.ext import commands, tasks
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime

# --- CẤU HÌNH BIẾN ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA = 1234567890  # ID Kênh hiển thị kèo bóng đá
ID_KENH_BXH = 1234567890      # ID Kênh hiển thị Bảng Xếp Hạng tự động

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

DB_PATH = '/app/economy.db'

# --- HÀM DATABASE TỐI ƯU ---
def update_db(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    conn.close()

def get_db(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    res = c.fetchone()
    conn.close()
    return res

def get_all(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    res = c.fetchall()
    conn.close()
    return res

@bot.event
async def on_ready():
    # Khởi tạo dữ liệu
    update_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0, inventory TEXT DEFAULT "")')
    update_db('CREATE TABLE IF NOT EXISTS shop (item_name TEXT PRIMARY KEY, price INTEGER)')
    
    # Chạy các vòng lặp tự động
    auto_upcoming_matches.start()
    auto_update_bxh.start()
    
    print(f'🚀 {bot.user} đã sẵn sàng vận hành hệ thống Casino & Football!')

# --- 1. HỆ THỐNG BẢNG XẾP HẠNG TỰ ĐỘNG (BXH) ---
@tasks.loop(minutes=30)
async def auto_update_bxh():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    
    users = get_all("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10", ())
    
    embed = discord.Embed(
        title="🏆 BẢNG XẾP HẠNG ĐẠI GIA SERVER",
        description="Top 10 người có số dư tài khoản cao nhất.",
        color=0xffd700, # Màu vàng Gold
        timestamp=datetime.utcnow()
    )
    
    if not users:
        embed.description = "Chưa có dữ liệu người chơi."
    else:
        for i, (user_id, coins) in enumerate(users, 1):
            user = bot.get_user(user_id)
            name = user.name if user else f"User ID: {user_id}"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
            embed.add_field(name=f"{medal} {name}", value=f"💰 `{coins:,}` Coins", inline=False)
    
    await channel.purge(limit=1)
    await channel.send(embed=embed)

# --- 2. HỆ THỐNG BÓNG ĐÁ & KÈO CHẤP ---
@tasks.loop(minutes=15)
async def auto_upcoming_matches():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    url = "https://v3.football.api-sports.io/fixtures?next=10"
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
    
    try:
        response = requests.get(url, headers=headers).json()
        matches = response.get('response', [])
        await channel.purge(limit=5)
        
        embed = discord.Embed(title="⚽ KÈO BÓNG ĐÁ & TỈ LỆ CHẤP", color=0x2ecc71, timestamp=datetime.utcnow())
        embed.set_description("🔔 *Kèo sẽ tự động đóng 15 phút trước giờ bóng lăn.*")
        
        now = datetime.utcnow()
        for m in matches:
            m_id = m['fixture']['id']
            home, away = m['teams']['home']['name'], m['teams']['away']['name']
            start_time = datetime.fromisoformat(m['fixture']['date'].replace('Z', '+00:00')).replace(tzinfo=None)
            
            diff = (start_time - now).total_seconds()
            status = "🔓 ĐANG MỞ" if diff > 900 else "🔒 ĐÃ ĐÓNG"
            handicap = (m_id % 3) * 0.5 + 0.5 # Giả lập tỉ lệ chấp

            embed.add_field(
                name=f"🆔 ID: {m_id} | ⏱ {start_time.strftime('%H:%M %d/%m')}",
                value=f"🏟 **{home}** (Chấp {handicap}) vs **{away}**\nTrạng thái: `{status}`",
                inline=False
            )
        embed.set_footer(text="Cú pháp: !cuoc [ID] [Đội] [Tiền]")
        await channel.send(embed=embed)
    except: pass

# --- 3. LỆNH CÁ CƯỢC & TÀI XỈU ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']:
        return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [tiền]`")

    res = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    balance = res[0] if res else 0
    if cuoc < 100 or balance < cuoc:
        return await ctx.send("⚠️ Bạn không đủ tiền hoặc cược quá thấp (Min 100)!")

    # Hiệu ứng chờ
    embed = discord.Embed(title="🎲 ĐANG LẮC XÚC XẮC...", color=0x3498db)
    embed.set_image(url="https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJpbmZqZ2N0Z2R6Z2R6Z2R6Z2R6Z2R6Z2R6Z2R6Z2R6JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/L20mbc7yBGdqE/giphy.gif")
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(2.5)

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    kq = "tai" if tong >= 11 else "xiu"
    win = (lua_chon == kq)
    
    new_bal = balance + cuoc if win else balance - cuoc
    update_db("INSERT OR REPLACE INTO users (user_id, coins) VALUES (?, ?)", (ctx.author.id, new_bal))

    res_embed = discord.Embed(title= "🎉 CHIẾN THẮNG!" if win else "💀 THẤT BẠI!", color= 0x2ecc71 if win else 0xe74c3c)
    res_embed.add_field(name="Kết quả", value=f"🎲 `{dices[0]}-{dices[1]}-{dices[2]}` = **{tong}**", inline=True)
    res_embed.add_field(name="Phân loại", value=f"💎 **{kq.upper()}**", inline=True)
    res_embed.add_field(name="Ví mới", value=f"`{new_bal:,}` Coins", inline=False)
    await msg.edit(embed=res_embed)

# --- 4. HỆ THỐNG VÍ & SHOP (ADMIN & USER) ---
@bot.command()
async def vi(ctx):
    res = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    coins = res[0] if res else 0
    embed = discord.Embed(title="💳 THÔNG TIN TÀI KHOẢN", color=0xf1c40f)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.add_field(name="👤 Người chơi", value=ctx.author.mention, inline=True)
    embed.add_field(name="💰 Số dư", value=f"`{coins:,}` Coins", inline=True)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def addshop(ctx, name: str, price: int):
    update_db("INSERT OR REPLACE INTO shop (item_name, price) VALUES (?, ?)", (name, price))
    await ctx.send(f"✅ Đã thêm vật phẩm **{name}** giá `{price:,}` vào Shop!")

@bot.command()
async def shop(ctx):
    items = get_all("SELECT * FROM shop", ())
    embed = discord.Embed(title="🛒 CỬA HÀNG VẬT PHẨM", color=0x9b59b6)
    if not items: embed.description = "Shop hiện tại chưa có hàng."
    for name, price in items:
        embed.add_field(name=f"📦 {name}", value=f"`{price:,}` Coins", inline=True)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    update_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    update_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
    await ctx.send(f"✅ Đã nạp `{amount:,}` Coins cho {member.mention}")

# --- LỆNH HƯỚNG DẪN (GIÚP NGƯỜI DÙNG TIẾP CẬN NHANH) ---
@bot.command()
async def trogiup(ctx):
    embed = discord.Embed(title="📚 HƯỚNG DẪN SỬ DỤNG BOT", color=0x3498db)
    embed.add_field(name="🎮 Minigame", value="`!taixiu [tai/xiu] [tiền]`\n`!cuoc [ID] [Đội] [tiền]`", inline=False)
    embed.add_field(name="💰 Tài khoản", value="`!vi`: Xem tiền\n`!shop`: Xem cửa hàng\n`!buy [Tên]`: Mua đồ", inline=False)
    embed.add_field(name="👑 Admin", value="`!nap [@user] [tiền]`\n`!addshop [Tên] [Giá]`", inline=False)
    await ctx.send(embed=embed)

bot.run(TOKEN)
