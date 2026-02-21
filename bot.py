import discord
from discord.ext import commands
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime

# --- LẤY BIẾN TỪ RAILWAY ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
DB_PATH = '/app/economy.db' # Phải dùng /app/ để khớp với Volume Railway

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
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    conn.close()
    print(f'🚀 Bot {bot.user} đã sẵn sàng chinh phục server!')

# --- LỆNH VÍ TIỀN (EMBED ĐẸP) ---
@bot.command()
async def vi(ctx):
    coins = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    coins = coins[0] if coins else 0
    
    embed = discord.Embed(
        title="💰 TÀI KHOẢN NGÂN HÀNG",
        description=f"Chào mừng **{ctx.author.display_name}** quay trở lại!",
        color=0xf1c40f,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Số dư hiện tại:", value=f"✨ `{coins:,}` Coins", inline=False)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.set_footer(text="Hãy nạp thêm để tiếp tục cuộc chơi!")
    await ctx.send(embed=embed)

# --- TÀI XỈU (HIỆU ỨNG LẮC) ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']:
        return await ctx.send("❌ Cú pháp đúng: `!taixiu [tai/xiu] [tiền]`")
    
    current_coins = get_db("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,))
    current_coins = current_coins[0] if current_coins else 0

    if cuoc < 100 or current_coins < cuoc:
        return await ctx.send("⚠️ Bạn không đủ tiền hoặc mức cược quá thấp (Min 100)!")

    # Embed đang lắc
    embed = discord.Embed(title="🎲 ĐANG LẮC XÚC XẮC...", color=0x3498db)
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(2)

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    ket_qua = "tai" if tong >= 11 else "xiu"
    win = (lua_chon == ket_qua)

    if win:
        update_db("UPDATE users SET coins = coins + ? WHERE user_id=?", (cuoc, ctx.author.id))
        color = 0x2ecc71
        title = "🎉 BẠN ĐÃ THẮNG!"
    else:
        update_db("UPDATE users SET coins = coins - ? WHERE user_id=?", (cuoc, ctx.author.id))
        color = 0xe74c3c
        title = "💀 BẠN ĐÃ THUA!"

    res_embed = discord.Embed(title=title, color=color)
    res_embed.add_field(name="Kết quả", value=f"🎲 `{dices[0]}` + `{dices[1]}` + `{dices[2]}` = **{tong}**", inline=True)
    res_embed.add_field(name="Lựa chọn", value=f"✨ {lua_chon.upper()}", inline=True)
    res_embed.add_field(name="Phân loại", value=f"💎 **{ket_qua.upper()}**", inline=True)
    res_embed.set_footer(text=f"Số dư mới: {get_db('SELECT coins FROM users WHERE user_id=?', (ctx.author.id,))[0]:,} Coins")
    
    await msg.edit(embed=res_embed)

# --- BÓNG ĐÁ TRỰC TIẾP (EMBED TỈ SỐ) ---
@bot.command()
async def bongda(ctx):
    if not API_KEY: return await ctx.send("Chưa cấu hình API Key!")
    
    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
    
    try:
        response = requests.get(url, headers=headers).json()
        matches = response.get('response', [])
        
        if not matches:
            return await ctx.send("⚽ Hiện tại không có trận đấu nào đang đá trực tiếp.")

        embed = discord.Embed(title="🔥 TỈ SỐ BÓNG ĐÁ TRỰC TIẾP", color=0xe67e22)
        
        for m in matches[:10]: # Hiển thị 10 trận nổi bật
            home = m['teams']['home']['name']
            away = m['teams']['away']['name']
            h_goal = m['goals']['home']
            a_goal = m['goals']['away']
            time = m['fixture']['status']['elapsed']
            m_id = m['fixture']['id']
            
            embed.add_field(
                name=f"🆔 ID: {m_id} | ⏱ {time}'",
                value=f"🏟 **{home}** `{h_goal}` - `{a_goal}` **{away}**",
                inline=False
            )
        
        embed.set_footer(text="Dùng !cuocbong [ID] [Tên_Đội] [Tiền] để đặt cược")
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Không thể kết nối tới dữ liệu bóng đá.")

# --- NẠP TIỀN (ADMIN) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    get_db("SELECT coins FROM users WHERE user_id=?", (member.id,)) # Tạo user nếu chưa có
    update_db("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, member.id))
    
    embed = discord.Embed(title="💳 GIAO DỊCH THÀNH CÔNG", color=0x2ecc71)
    embed.add_field(name="Người nhận:", value=member.mention, inline=True)
    embed.add_field(name="Số tiền:", value=f"`{amount:,}` Coins", inline=True)
    embed.set_footer(text="Hệ thống nạp tiền tự động bởi Admin")
    await ctx.send(embed=embed)

bot.run(TOKEN)
