import discord
from discord.ext import commands, tasks
import sqlite3
import random
import os
import requests
from datetime import datetime, timedelta

# --- CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981

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
    update_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    auto_upcoming_matches.start()
    auto_update_bxh.start()
    print(f'🚀 Bot {bot.user} đã lên sàn! Kênh bóng đá và BXH đã sẵn sàng.')

# --- 🏆 TỰ ĐỘNG CẬP NHẬT BXH COIN (EMBED XỊN) ---
@tasks.loop(minutes=5)
async def auto_update_bxh():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    
    conn = sqlite3.connect(DB_PATH)
    users = conn.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10").fetchall()
    conn.close()
    
    embed = discord.Embed(
        title="🏆 BẢNG XẾP HẠNG ĐẠI GIA SERVER 🏆",
        description="*Những người đang nắm giữ quyền lực tài chính lớn nhất*",
        color=0xf1c40f, # Màu vàng kim loại
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url="https://i.imgur.com/vM0W39S.png") # Icon cup vàng
    
    if not users:
        embed.description = "💳 Hiện chưa có dữ liệu giao dịch."
    else:
        for i, (u_id, coins) in enumerate(users, 1):
            member = bot.get_user(u_id)
            name = member.display_name if member else f"Người dùng ẩn ({u_id})"
            
            # Icon thứ hạng
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
            embed.add_field(
                name=f"{medal} {name}",
                value=f"💰 Tài sản: **{coins:,}** Coins",
                inline=False
            )
            
    embed.set_footer(text="Cập nhật tự động 5 phút/lần • Hãy chơi !taixiu để lên Top!")
    
    # Xóa tin nhắn cũ để BXH luôn nằm ở cuối hoặc duy nhất
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed)

# --- ⚽ LIVESCORE & KÈO BÓNG ĐÁ ---
@tasks.loop(minutes=2)
async def auto_upcoming_matches():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        response = requests.get(url, headers=headers).json()
        matches = response.get('matches', [])
        active_matches = [m for m in matches if m['status'] in ['IN_PLAY', 'PAUSED', 'TIMED', 'SCHEDULED']]
        
        await channel.purge(limit=5, check=lambda m: m.author == bot.user)
        
        has_live = any(m['status'] == 'IN_PLAY' for m in active_matches)
        embed_color = 0xff0000 if has_live else 0x2ecc71
        
        embed = discord.Embed(
            title="⚽ BẢNG TIN BÓNG ĐÁ TRỰC TUYẾN ⚽",
            description=f"🏠 **Trạng thái:** {'🔴 ĐANG CÓ TRẬN ĐẤU' if has_live else '🟢 Chờ trận đấu mới'}",
            color=embed_color,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url="https://i.imgur.com/8E98v90.png")

        if not active_matches:
            embed.description = "💤 Hiện tại không có giải đấu lớn nào diễn ra."
        else:
            for m in active_matches[:8]:
                home = m['homeTeam']['name']
                away = m['awayTeam']['name']
                league = m['competition']['name']
                status = m['status']
                
                s_h = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
                s_a = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0
                
                if status == 'IN_PLAY':
                    display = f"🔴 **LIVE: {s_h} - {s_a}**"
                    info = "⚡ Trận đấu đang diễn ra cực nóng!"
                elif status == 'PAUSED':
                    display = f"⏸️ **HT: {s_h} - {s_a}**"
                    info = "Nghỉ giữa hiệp"
                else:
                    time_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
                    display = "🆚 Chưa đá"
                    info = f"⏰ Giờ VN: `{time_vn}`"

                embed.add_field(
                    name=f"🏆 {league}",
                    value=f"🏟️ **{home}** {display} **{away}**\n📝 {info}\n🆔 ID: `{m['id']}`\n━━━━━━━━━━━━━",
                    inline=False
                )
        
        embed.set_footer(text="Tỉ số & Kèo cập nhật tự động 2 phút/lần")
        await channel.send(embed=embed)
    except: pass

# --- 🎲 TRÒ CHƠI TÀI XỈU ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: int):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']: return
    
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,)).fetchone()
    balance = res[0] if res else 0
    
    if balance < cuoc or cuoc < 100:
        return await ctx.send(embed=discord.Embed(title="❌ Số dư không đủ!", color=0xff0000))

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    kq = "tai" if tong >= 11 else "xiu"
    win = (lua_chon == kq)
    
    new_bal = balance + cuoc if win else balance - cuoc
    update_db("INSERT OR REPLACE INTO users (user_id, coins) VALUES (?, ?)", (ctx.author.id, new_bal))

    embed = discord.Embed(title="🎉 THẮNG!" if win else "💸 THUA!", color=0xf1c40f if win else 0xe74c3c)
    embed.add_field(name="🎲 Xúc xắc", value=f"```| {dices[0]} | {dices[1]} | {dices[2]} |```", inline=True)
    embed.add_field(name="Kết quả", value=f"✨ **{tong}** ({kq.upper()})", inline=True)
    embed.set_footer(text=f"Số dư mới: {new_bal:,} Coins")
    await ctx.send(embed=embed)

# --- 💳 VÍ & NẠP ---
@bot.command()
async def vi(ctx):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT coins FROM users WHERE user_id=?", (ctx.author.id,)).fetchone()
    conn.close()
    coins = res[0] if res else 0
    embed = discord.Embed(title="💳 VÍ TIỀN", description=f"Số dư: **{coins:,}** Coins", color=0x3498db)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    update_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    update_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
    await ctx.send(f"✅ Đã nạp **{amount:,}** Coins cho {member.mention}")

bot.run(TOKEN)
