import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- CẤU HÌNH BIẾN MÔI TRƯỜNG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BXH = 1474674662792232981         
ID_BONG_DA = 1474672512708247582     

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- XỬ LÝ DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

history_points = []

# ================= 1. GIAO DIỆN BÓNG ĐÁ (LOGO & TỈ SỐ CHUẨN) =================
@tasks.loop(minutes=1)
async def auto_scoreboard_update():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = [m for m in res.get('matches', []) if m['status'] in ["IN_PLAY", "PAUSED", "TIMED", "LIVE"]][:3]
        
        await channel.purge(limit=5, check=lambda m: m.author == bot.user)

        for m in matches:
            h_name, a_name = m['homeTeam']['shortName'], m['awayTeam']['shortName']
            h_score = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
            a_score = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0
            
            start_dt = datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00'))
            now_dt = datetime.now(timezone.utc)
            diff = (start_dt - now_dt).total_seconds() / 60
            
            # Trạng thái cược
            if m['status'] in ["IN_PLAY", "PAUSED", "LIVE"] or diff <= 15:
                bet_status = "🔒 ĐÃ ĐÓNG ĐẶT CƯỢC"
                status_color = 0xff4d4d
            else:
                status_color = 0x2ecc71
                bet_status = f"✅ ĐANG MỞ (Đóng sau {int(diff-15)}p)"

            embed = discord.Embed(color=status_color)
            embed.set_author(name=f"Trận đấu đang diễn ra: {m['status']}")
            
            # Layout Logo và Tỉ số thẳng hàng theo hình
            embed.add_field(name="Đội bóng", value=f"🛡️ **{h_name}**\n🛡️ **{a_name}**", inline=True)
            embed.add_field(name="Tỉ số", value=f"**{h_score}**\n**{a_score}**", inline=True)
            
            if m['homeTeam'].get('crest'): embed.set_thumbnail(url=m['homeTeam'].get('crest'))
            
            embed.add_field(name="📌 Thông tin cược", value=f"**{bet_status}**", inline=False)
            embed.set_footer(text=f"ID Trận: {m['id']} | Cú pháp: !cuoc {m['id']} [chu/khach] [số tiền]")
            await channel.send(embed=embed)
    except: pass

# ================= 2. MODAL CƯỢC & GỬI VÉ QUA DM =================
@bot.command()
async def cuoc(ctx, match_id: int, side: str, amount: int):
    side = side.lower()
    if side not in ["chu", "khach"]: return await ctx.send("❌ Chọn `chu` hoặc `khach`!")
    
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Ví của bạn không đủ Cash!")

    try:
        res = requests.get(f"https://api.football-data.org/v4/matches/{match_id}", headers={"X-Auth-Token": API_KEY}).json()
        # Trừ tiền và lưu vé
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
        query_db("INSERT INTO bets (user_id, match_id, side, amount, status) VALUES (?, ?, ?, ?, 'PENDING')", 
                 (ctx.author.id, match_id, side, amount))

        # Gửi vé qua DM (Embed sang trọng)
        ticket = discord.Embed(title="🎫 VÉ CƯỢC BÓNG ĐÁ THÀNH CÔNG", color=0x3498db)
        ticket.add_field(name="👤 Người cược", value=ctx.author.name, inline=True)
        ticket.add_field(name="🕒 Thời gian", value=datetime.now().strftime("%d/%m/%Y %H:%M:%S"), inline=True)
        ticket.add_field(name="🛡️ Trận đấu", value=f"{res['homeTeam']['name']} vs {res['awayTeam']['name']}", inline=False)
        ticket.add_field(name="🎯 Lựa chọn", value=side.upper(), inline=True)
        ticket.add_field(name="💰 Số tiền", value=f"{amount:,} Cash", inline=True)
        
        await ctx.author.send(embed=ticket)
        await ctx.send(f"✅ {ctx.author.mention} đã đặt cược thành công! Kiểm tra DM để nhận vé.")
    except:
        await ctx.send("❌ Không tìm thấy thông tin trận đấu!")

# ================= 3. TÀI XỈU 3-18 & SOI CẦU (47% THẮNG) =================
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_points
    side = side.lower()
    user_coins = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_coins or user_coins[0] < amount: return await ctx.send("❌ Không đủ tiền!")

    # Logic tỉ lệ 47% thắng
    is_win = random.randint(1, 100) <= 47
    d1, d2, d3 = [random.randint(1, 6) for _ in range(3)]
    total = d1 + d2 + d3
    res_side = "tai" if total >= 11 else "xiu"

    if (is_win and res_side != side) or (not is_win and res_side == side):
        total = random.randint(11, 18) if side == "tai" and is_win else random.randint(3, 10)
        if not is_win: total = random.randint(3, 10) if side == "tai" else random.randint(11, 18)
        # Random lại xúc xắc cho khớp tổng
        d1 = random.randint(1, min(6, total-2)); d2 = random.randint(1, min(6, total-d1-1)); d3 = total - d1 - d2
        res_side = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount if side == res_side else -amount, ctx.author.id))
    history_points.append(total)

    # Embed Tài Xỉu giống hình
    embed = discord.Embed(title="🎉 Kết quả phiên tài xỉu 🪙", color=0xff4d4d if side != res_side else 0x2ecc71)
    embed.add_field(name="🎲 Xúc xắc", value=f"**{d1} - {d2} - {d3}**", inline=False)
    embed.add_field(name="🎯 Tổng số điểm", value=f"**{total}**", inline=True)
    embed.add_field(name="📝 Kết quả", value=f"**{res_side.upper()}**", inline=True)
    embed.set_footer(text="Hệ thống Verdict Cash", icon_url=ctx.author.avatar.url)
    
    view = ui.View()
    view.add_item(ui.Button(label="Lịch sử phiên", style=discord.ButtonStyle.grey, custom_id="history"))
    await ctx.send(embed=embed, view=view)

@bot.command()
async def cau(ctx):
    pts = history_points[-15:]
    graph = "```\n"
    for lvl in range(18, 2, -3):
        graph += f"{lvl:02} |" + "".join([" ● " if abs(p-lvl) < 2 else "   " for p in pts]) + "\n"
    graph += "   " + "---" * len(pts) + "\n```"
    await ctx.send(embed=discord.Embed(title="📊 Biểu đồ soi cầu Tài Xỉu", description=graph, color=0xf1c40f))

# ================= 4. BXH ĐẠI GIA & VÍ =================
@tasks.loop(minutes=5)
async def update_bxh():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="🏆 BẢNG XẾP HẠNG ĐẠI GIA VERDICT", color=0xffd700)
    for i, (uid, coins) in enumerate(top):
        embed.add_field(name=f"Top {i+1}", value=f"<@{uid}>: `{coins:,}` Cash", inline=False)
    await channel.purge(limit=1); await channel.send(embed=embed)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    embed = discord.Embed(title="💳 VÍ TIỀN CỦA BẠN", description=f"Số dư hiện tại: **{d[0] if d else 0:,}** Cash", color=0x2ecc71)
    view = ui.View()
    view.add_item(ui.Button(label="Nạp tiền", style=discord.ButtonStyle.green))
    await ctx.send(embed=embed, view=view)

# ================= 5. KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, status TEXT)')
    auto_scoreboard_update.start(); update_bxh.start()
    print("🚀 Bot Verdict Final đã online!")

bot.run(TOKEN)
