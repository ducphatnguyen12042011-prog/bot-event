import discord
from discord.ext import commands, tasks
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Tải biến môi trường
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582 
ID_BXH = 1474674662792232981
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

# ================= 1. TỰ ĐỘNG HIỂN THỊ TRẬN ĐẤU =================
@tasks.loop(minutes=15)
async def auto_update_matches():
    global current_matches
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        # Gọi API lấy trận đấu Ngoại Hạng Anh
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:5]
        current_matches = {str(m['id']): m for m in matches}

        await channel.purge(limit=15, check=lambda m: m.author == bot.user)
        
        for mid, m in current_matches.items():
            h_name, a_name = m['homeTeam']['name'], m['awayTeam']['name']
            h_icon, a_icon = m['homeTeam'].get('crest'), m['awayTeam'].get('crest')
            start_dt = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
            hdp = 0.5 # Kèo chấp mặc định (Chủ chấp 0.5)

            # Embed thiết kế đối xứng logo
            embed = discord.Embed(
                title=f"{h_name}  vs  {a_name}",
                description=f"⚖️ **Kèo: {h_name} chấp {hdp}**\n━━━━━━━━━━━━━━━━━━━━",
                color=0x37003c 
            )
            embed.set_author(name="PREMIER LEAGUE", icon_url=h_icon)
            embed.set_thumbnail(url=a_icon)
            
            embed.add_field(name="🆔 Mã trận", value=f"`{mid}`", inline=True)
            embed.add_field(name="⏰ Khởi tranh", value=f"<t:{int(start_dt.timestamp())}:R>", inline=True)
            embed.set_footer(text="Cú pháp: !cuoc <mã> <chu/khach> <số_tiền>")
            
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Lỗi hiển thị: {e}")

# ================= 2. HỆ THỐNG TRẢ THƯỞNG TỰ ĐỘNG =================
@tasks.loop(minutes=30)
async def auto_payout():
    # Lấy các đơn cược đang chờ xử lý
    pending_bets = query_db("SELECT id, user_id, match_id, amount, team, hdp FROM bets WHERE status = 'PENDING'")
    if not pending_bets: return

    for b_id, u_id, m_id, amt, b_team, hdp in pending_bets:
        try:
            r = requests.get(f"https://api.football-data.org/v4/matches/{m_id}", headers={"X-Auth-Token": API_KEY}).json()
            
            if r.get('status') == 'FINISHED':
                h_score = r['score']['fullTime']['home']
                a_score = r['score']['fullTime']['away']
                h_name = r['homeTeam']['name']
                
                # Logic tính thắng thua dựa trên kèo chấp
                is_home_bet = (b_team == h_name)
                if is_home_bet:
                    win = (h_score + hdp > a_score)
                else:
                    win = (a_score + abs(hdp) > h_score)

                if win:
                    # Thắng cộng x2 (vốn + lời)
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt * 2, u_id))
                    status = "WIN"
                else:
                    status = "LOSE"

                query_db("UPDATE bets SET status = ? WHERE id = ?", (status, b_id))
        except: continue

# ================= 3. LỆNH ĐẶT CƯỢC =================
@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    if match_id not in current_matches:
        return await ctx.send("❌ Mã trận không tồn tại!")
    if amount < 100:
        return await ctx.send("❌ Cược tối thiểu 100 xu ảo.")

    user_coins = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_coins or user_coins[0] < amount:
        return await ctx.send("❌ Bạn không đủ xu!")

    match = current_matches[match_id]
    team_bet = match['homeTeam']['name'] if side.lower() in ["chu", "home"] else match['awayTeam']['name']
    hdp = 0.5 if side.lower() in ["chu", "home"] else -0.5

    # Trừ tiền và lưu đơn
    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, ?, ?, ?, ?, 'PENDING')", 
             (ctx.author.id, match_id, amount, team_bet, hdp))
    
    await ctx.send(f"✅ {ctx.author.mention} cược thành công **{amount:,}** xu cho **{team_bet}**")

# ================= 4. VÍ, NẠP TIỀN & BXH =================
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 {ctx.author.mention}, ví của bạn có: **{d[0] if d else 0:,}** xu ảo.")

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    # Kiểm tra quyền Admin dựa trên ID role bạn cung cấp
    if any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu cho {member.mention}")
    else:
        await ctx.send("❌ Bạn không có quyền Admin!")

@tasks.loop(minutes=20)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="🏆 TOP ĐẠI GIA NGOẠI HẠNG ANH", color=0xf1c40f)
    embed.description = "\n".join([f"**#{i+1}** <@{u}>: `{c:,}` xu" for i, (u, c) in enumerate(top)])
    await channel.purge(limit=2); await channel.send(embed=embed)

# ================= KHỞI CHẠY =================
@bot.event
async def on_ready():
    # Khởi tạo Database
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    
    # Chạy các vòng lặp tự động
    auto_update_matches.start()
    update_leaderboard.start()
    auto_payout.start()
    
    print("🚀 Bot Final Version đã online! Hệ thống vận hành hoàn toàn tự động.")

bot.run(TOKEN)
