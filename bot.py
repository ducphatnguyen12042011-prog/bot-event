import discord
from discord.ext import commands, tasks
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime

# --- CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA =1474672512708247582  # Thay ID kênh kèo
ID_KENH_BXH = 1474674662792232981    # Thay ID kênh BXH

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

def get_db(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    res = c.fetchone()
    conn.close()
    return res

@bot.event
async def on_ready():
    update_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0, inventory TEXT DEFAULT "")')
    update_db('CREATE TABLE IF NOT EXISTS shop (item_name TEXT PRIMARY KEY, price INTEGER)')
    auto_upcoming_matches.start()
    auto_update_bxh.start()
    print(f'🚀 {bot.user} đã online!')

# --- 🏆 BẢNG XẾP HẠNG TỰ ĐỘNG ---
@tasks.loop(minutes=30)
async def auto_update_bxh():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    
    conn = sqlite3.connect(DB_PATH)
    users = conn.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10").fetchall()
    conn.close()
    
    embed = discord.Embed(title="🏆 BẢNG XẾP HẠNG ĐẠI GIA", color=0xffd700, timestamp=datetime.utcnow())
    for i, (u_id, coins) in enumerate(users, 1):
        member = bot.get_user(u_id)
        name = member.name if member else f"User {u_id}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        embed.add_field(name=f"{medal} {name}", value=f"💰 `{coins:,}` Coins", inline=False)
    
    await channel.purge(limit=1)
    await channel.send(embed=embed)

# --- ⚽ BÓNG ĐÁ & KÈO CHẤP ---
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
        
        embed = discord.Embed(title="⚽ KÈO BÓNG ĐÁ HÔM NAY", color=0x2ecc71)
        now = datetime.utcnow()
        for m in matches:
            m_id = m['fixture']['id']
            home, away = m['teams']['home']['name'], m['teams']['away']['name']
            start_time = datetime.fromisoformat(m['fixture']['date'].replace('Z', '+00:00')).replace(tzinfo=None)
            
            diff = (start_time - now).total_seconds()
            status = "🔓 ĐANG MỞ" if diff > 900 else "🔒 ĐÃ ĐÓNG"
            handicap = (m_id % 3) * 0.5 + 0.5 

            embed.add_field(
                name=f"🆔 {m_id} | ⏱ {start_time.strftime('%H:%M %d/%m')}",
                value=f"🏟 **{home}** (Chấp {handicap}) vs **{away}**\nTrạng thái: `{status}`",
                inline=False
            )
        await channel.send(embed=embed)
    except: pass

# --- 🎲 TÀI XỈU ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']: return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [tiền]`")

    res = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    balance = res[0] if res else 0
    if cuoc < 100 or balance < cuoc: return await ctx.send("⚠️ Bạn không đủ tiền!")

    dices = [random.randint(1, 6) for _ in range(3)]
    tong, kq = sum(dices), ("tai" if sum(dices) >= 11 else "xiu")
    win = (lua_chon == kq)
    
    new_bal = balance + cuoc if win else balance - cuoc
    update_db("INSERT OR REPLACE INTO users (user_id, coins) VALUES (?, ?)", (ctx.author.id, new_bal))

    embed = discord.Embed(title="🎲 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if win else 0xe74c3c)
    embed.add_field(name="Xúc xắc", value=f"🎲 `{dices[0]}-{dices[1]}-{dices[2]}` = **{tong}**", inline=True)
    embed.add_field(name="Kết quả", value=f"✨ **{kq.upper()}**", inline=True)
    embed.set_footer(text=f"Ví hiện tại: {new_bal:,} Coins")
    await ctx.send(embed=embed)

# --- 🛒 SHOP & ADMIN ---
@bot.command()
@commands.has_permissions(administrator=True)
async def addshop(ctx, name: str, price: int):
    update_db("INSERT OR REPLACE INTO shop (item_name, price) VALUES (?, ?)", (name, price))
    await ctx.send(f"✅ Đã thêm **{name}** giá `{price:,}` vào Shop!")

@bot.command()
async def shop(ctx):
    conn = sqlite3.connect(DB_PATH)
    items = conn.execute("SELECT * FROM shop").fetchall()
    conn.close()
    embed = discord.Embed(title="🛒 CỬA HÀNG", color=0x9b59b6)
    for name, price in items:
        embed.add_field(name=f"📦 {name}", value=f"`{price:,}` Coins", inline=True)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    update_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    update_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
    await ctx.send(f"✅ Đã nạp `{amount:,}` Coins cho {member.mention}")

@bot.command()
async def vi(ctx):
    res = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{res[0] if res else 0:,} Coins**")

bot.run(TOKEN)
