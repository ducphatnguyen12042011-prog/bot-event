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
# Thay số này bằng ID kênh bạn muốn bot tự hiện bảng tỉ số
ID_KENH_BONG_DA = 123456789012345678 

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Đường dẫn DB trên Railway Volume
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
    update_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    update_db('''CREATE TABLE IF NOT EXISTS bets 
                 (id INTEGER PRIMARY KEY, user_id INTEGER, match_id INTEGER, team TEXT, amount INTEGER, handicap REAL)''')
    auto_bongda.start()
    print(f'🚀 Bot {bot.user} đã sẵn sàng!')

# --- TỰ ĐỘNG HIỂN THỊ BÓNG ĐÁ & KÈO CHẤP ---
@tasks.loop(minutes=5)
async def auto_bongda():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return

    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
    
    try:
        response = requests.get(url, headers=headers).json()
        matches = response.get('response', [])
        
        await channel.purge(limit=5) # Xóa tin cũ cho sạch
        
        embed = discord.Embed(title="🔥 BẢNG KÈO & TỈ SỐ TRỰC TIẾP", color=0xe67e22, timestamp=datetime.utcnow())
        
        if not matches:
            embed.description = "Hiện tại không có trận đấu nào đang diễn ra."
            await channel.send(embed=embed)
            return

        for m in matches[:10]:
            m_id = m['fixture']['id']
            home = m['teams']['home']['name']
            away = m['teams']['away']['name']
            score = f"{m['goals']['home']} - {m['goals']['away']}"
            time = m['fixture']['status']['elapsed']
            
            # Bot tự tính kèo chấp dựa trên ID trận (để kèo không bị nhảy liên tục)
            handicap = (m_id % 4) * 0.25 + 0.5 
            
            embed.add_field(
                name=f"🆔 ID: {m_id} | ⏱ {time}'",
                value=f"🏟 **{home}** (Chấp {handicap}) vs **{away}**\n📊 Tỉ số: `{score}`",
                inline=False
            )
        
        embed.set_footer(text="Dùng !cuoc [ID] [Tên_Đội] [Số_Tiền] để đặt cược")
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Lỗi bóng đá: {e}")

# --- LỆNH ĐẶT CƯỢC BÓNG ĐÁ ---
@bot.command()
async def cuoc(ctx, match_id: int, team: str, amount: int):
    coins = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    balance = coins[0] if coins else 0
    
    if amount < 100 or balance < amount:
        return await ctx.send("❌ Bạn không đủ tiền hoặc cược quá ít (Min 100)!")

    update_db("UPDATE users SET coins = coins - ? WHERE user_id=?", (amount, ctx.author.id))
    update_db("INSERT INTO bets (user_id, match_id, team, amount) VALUES (?, ?, ?, ?)", 
              (ctx.author.id, match_id, team, amount))
    
    embed = discord.Embed(title="✅ ĐẶT CƯỢC THÀNH CÔNG", color=0x2ecc71)
    embed.add_field(name="Trận ID", value=match_id, inline=True)
    embed.add_field(name="Đội chọn", value=team, inline=True)
    embed.add_field(name="Tiền cược", value=f"{amount:,} Coins", inline=True)
    await ctx.send(embed=embed)

# --- TÀI XỈU TỰ ĐỘNG ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']:
        return await ctx.send("Cú pháp: `!taixiu [tai/xiu] [tiền]`")

    coins = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    balance = coins[0] if coins else 0
    if cuoc < 100 or balance < cuoc:
        return await ctx.send("❌ Bạn không đủ tiền!")

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    ket_qua = "tai" if tong >= 11 else "xiu"
    
    msg = await ctx.send("🎲 **Đang lắc...**")
    await asyncio.sleep(2)

    if lua_chon == ket_qua:
        update_db("UPDATE users SET coins = coins + ? WHERE user_id=?", (cuoc, ctx.author.id))
        embed = discord.Embed(title="🎉 BẠN THẮNG!", color=0x2ecc71)
    else:
        update_db("UPDATE users SET coins = coins - ? WHERE user_id=?", (cuoc, ctx.author.id))
        embed = discord.Embed(title="💀 BẠN THUA!", color=0xe74c3c)

    embed.description = f"Kết quả: **{dices[0]} {dices[1]} {dices[2]}** = **{tong}** ({ket_qua.upper()})"
    embed.set_footer(text=f"Số dư mới: {get_db('SELECT coins FROM users WHERE user_id=?', (ctx.author.id,))[0]:,} Coins")
    await msg.edit(content=None, embed=embed)

# --- QUẢN LÝ TÀI KHOẢN (ADMIN) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    update_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    update_db("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, member.id))
    await ctx.send(f"💰 Đã nạp **{amount:,} Coins** cho {member.mention}")

@bot.command()
async def vi(ctx):
    coins = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{coins[0] if coins else 0:,} Coins**")

bot.run(TOKEN)
