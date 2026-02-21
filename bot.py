import discord
from discord.ext import commands, tasks
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582 # ID kênh hiển thị trận đấu
ID_BXH = 1474674662792232981    # ID kênh bảng xếp hạng
ADMIN_ROLE_ID = 1465374336214106237

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================= DATABASE =================
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

current_matches = {}

# ================= 1. TỰ ĐỘNG HIỂN THỊ TRẬN ĐẤU (TEXT ONLY) =================
@tasks.loop(minutes=15)
async def auto_update_matches():
    global current_matches
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:5]
        current_matches = {str(m['id']): m for m in matches}

        await channel.purge(limit=10, check=lambda m: m.author == bot.user)
        content = "⚽ **DANH SÁCH TRẬN ĐẤU ĐANG MỞ** ⚽\n━━━━━━━━━━━━━━━━━━━━\n"
        for mid, m in current_matches.items():
            start_dt = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
            content += f"🆔 Mã: `{mid}`\n⚔️ {m['homeTeam']['name']} vs {m['awayTeam']['name']}\n⏰ <t:{int(start_dt.timestamp())}:F>\n⚖️ Kèo: Chủ chấp 0.5\n----------------------------\n"
        content += "\n📝 Cú pháp: `!cuoc <mã> <chu/khach> <số_tiền>`"
        await channel.send(content)
    except: pass

# ================= 2. LỆNH ĐẶT CƯỢC =================
@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    if match_id not in current_matches:
        return await ctx.send("❌ Mã trận không tồn tại hoặc đã đóng!")
    if amount < 100:
        return await ctx.send("❌ Cược tối thiểu 100 xu.")

    match = current_matches[match_id]
    start_dt = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
    if datetime.utcnow() > (start_dt - timedelta(minutes=15)):
        return await ctx.send("⚠️ Trận đấu đã khóa cược!")

    user_coins = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_coins or user_coins[0] < amount:
        return await ctx.send("❌ Bạn không đủ xu!")

    team_name = match['homeTeam']['name'] if side.lower() == "chu" else match['awayTeam']['name']
    hdp = 0.5 if side.lower() == "chu" else -0.5

    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, ?, ?, ?, ?, 'PENDING')", 
             (ctx.author.id, match_id, amount, team_name, hdp))
    await ctx.send(f"✅ {ctx.author.mention} cược **{amount:,}** xu cho **{team_name}**")

# ================= 3. LỆNH VÍ TIỀN =================
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    await ctx.send(f"💳 {ctx.author.mention}, số dư của bạn: **{coins:,}** xu ảo.")

# ================= 4. LỆNH NẠP TIỀN (CHỈ ADMIN) =================
@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu cho {member.mention}")
    else:
        await ctx.send("❌ Bạn không có quyền sử dụng lệnh này!")

# ================= 5. TỰ ĐỘNG BẢNG XẾP HẠNG =================
@tasks.loop(minutes=20)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="🏆 BẢNG XẾP HẠNG ĐẠI GIA", color=0xf1c40f)
    desc = ""
    for i, (uid, coins) in enumerate(top):
        desc += f"**#{i+1}** <@{uid}>: `{coins:,}` xu\n"
    embed.description = desc or "Chưa có dữ liệu."
    await channel.purge(limit=2); await channel.send(embed=embed)

# ================= KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    auto_update_matches.start()
    update_leaderboard.start()
    print("🚀 Bot đã sẵn sàng - Hệ thống Coin & Lệnh đã kích hoạt!")

bot.run(TOKEN)
