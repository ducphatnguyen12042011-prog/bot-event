import discord
from discord.ext import commands
import sqlite3
import random
import os
import requests
import asyncio

# Lấy biến môi trường từ Railway
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- DATABASE (Lưu tiền và dữ liệu) ---
def init_db():
    conn = sqlite3.connect('economy.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def get_coins(user_id):
    conn = sqlite3.connect('economy.db')
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    if not res:
        conn = sqlite3.connect('economy.db')
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id, coins) VALUES (?, 0)", (user_id,))
        conn.commit()
        conn.close()
        return 0
    return res[0]

def update_coins(user_id, amount):
    conn = sqlite3.connect('economy.db')
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    init_db()
    print(f'Bot {bot.user} đang chạy trên Railway!')

# --- LỆNH NẠP TIỀN (CHỈ ADMIN) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    update_coins(member.id, amount)
    await ctx.send(f"✅ Đã nạp **{amount:,} Coins** cho {member.mention}!")

# --- TÀI XỈU (RANDOM TỰ ĐỘNG) ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']:
        return await ctx.send("Sử dụng: `!taixiu [tai/xiu] [tiền]`")
    
    balance = get_coins(ctx.author.id)
    if cuoc < 10 or balance < cuoc:
        return await ctx.send("❌ Bạn không đủ tiền hoặc mức cược quá thấp!")

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    ket_qua = "tai" if tong >= 11 else "xiu"
    
    msg = await ctx.send("🎲 Đang lắc...")
    await asyncio.sleep(2)

    if lua_chon == ket_qua:
        update_coins(ctx.author.id, cuoc)
        await msg.edit(content=f"🎲 Kết quả: {dices} = **{tong} ({ket_qua.upper()})**. Bạn **THẮNG** {cuoc:,}!")
    else:
        update_coins(ctx.author.id, -cuoc)
        await msg.edit(content=f"🎲 Kết quả: {dices} = **{tong} ({ket_qua.upper()})**. Bạn **THUA** {cuoc:,}!")

# --- BÓNG ĐÁ TRỰC TIẾP ---
@bot.command()
async def bongda(ctx):
    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
    try:
        data = requests.get(url, headers=headers).json()
        matches = data.get('response', [])
        if not matches: return await ctx.send("⚽ Hiện không có trận nào trực tiếp.")
        
        embed = discord.Embed(title="⚽ KÈO TRỰC TIẾP", color=0x00ff00)
        for m in matches[:5]:
            embed.add_field(name=f"ID: {m['fixture']['id']}", value=f"{m['teams']['home']['name']} vs {m['teams']['away']['name']}", inline=False)
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Lỗi lấy dữ liệu bóng đá.")

@bot.command()
async def vi(ctx):
    await ctx.send(f"💰 Ví của {ctx.author.mention}: **{get_coins(ctx.author.id):,} Coins**")

bot.run(TOKEN)
