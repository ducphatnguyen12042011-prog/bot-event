import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ADMIN_ROLE_ID = 1465374336214106237 
ID_BXH = 1474674662792232981        
ID_BONG_DA = 1474672512708247582    

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================= DATABASE & LOGIC CẦU =================
history_cau = [] # Lưu danh sách: {"res": "T/X", "val": tổng_số_nút}

def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

current_matches = {}

# ================= UI: VÍ & LỊCH SỬ =================
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.button(label="📜 Xem lịch sử đặt cược", style=discord.ButtonStyle.grey)
    async def history(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Đây không phải ví của bạn!", ephemeral=True)
        
        history = query_db("SELECT team, amount, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        if not history:
            return await interaction.response.send_message("📭 Bạn chưa có giao dịch nào.", ephemeral=True)
        
        embed = discord.Embed(title="📜 LỊCH SỬ 5 GIAO DỊCH GẦN NHẤT", color=0x3498db)
        desc = ""
        for team, amt, status in history:
            icon = "✅" if "WIN" in status else ("⏳" if "PENDING" in status else "❌")
            desc += f"{icon} **{team}** | Tiền: `{amt:,}` | KQ: `{status}`\n"
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= 1. GIAO DIỆN BÓNG ĐÁ (KÉO DÀI & ĐỐI XỨNG) =================
@tasks.loop(minutes=15)
async def auto_update_matches():
    global current_matches
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:5]
        current_matches = {str(m['id']): m for m in matches}
        await channel.purge(limit=15, check=lambda m: m.author == bot.user)

        for mid, m in current_matches.items():
            h_name = m['homeTeam']['shortName'] or m['homeTeam']['name']
            a_name = m['awayTeam']['shortName'] or m['awayTeam']['name']
            h_icon, a_icon = m['homeTeam'].get('crest'), m['awayTeam'].get('crest')
            h_score = m['score']['fullTime']['home'] or 0
            a_score = m['score']['fullTime']['away'] or 0
            start_dt = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ')

            embed = discord.Embed(title="🏆 THÔNG TIN TRẬN ĐẤU ĐANG DIỄN RA 🏆", color=0x2b2d31)
            embed.description = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            embed.set_author(name=f"{h_name}", icon_url=h_icon)
            embed.set_thumbnail(url=a_icon)
            
            # Kéo dài giao diện bằng code block tỉ số
            embed.add_field(name="📊 TỈ SỐ HIỆN TẠI", value=f"```py\n{h_name} {h_score} — {a_score} {a_name}\n```", inline=False)

            embed.add_field(name="🏠 CHỦ NHÀ", value=f"**{h_name}**\nKèo: `- 0.5`", inline=True)
            embed.add_field(name="✈️ SÂN KHÁCH", value=f"**{a_name}**\nKèo: `+ 0.5`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name="📅 CHI TIẾT", value=f"⏰ **Bắt đầu:** <t:{int(start_dt.timestamp())}:R>\n🆔 **Mã trận:** `{mid}`", inline=False)
            embed.add_field(name="📝 CÚ PHÁP CƯỢC", value=f"```fix\n!cuoc {mid} <chu/khach> <số_tiền>\n```", inline=False)
            
            await channel.send(embed=embed)
    except: pass

# ================= 2. TÀI XỈU 60% & SOI CẦU BIỂU ĐỒ =================
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_cau
    side = side.lower()
    if side not in ['tai', 'xiu']: return await ctx.send("❌ Cú pháp: `!taixiu tai/xiu <tiền>`")
    
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Không đủ Verdict Cash!")

    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    msg = await ctx.send(f"🎲 **{ctx.author.name}** đang lắc...")
    await asyncio.sleep(2)

    # Tỉ lệ thua 60%
    is_rigged = random.randint(1, 100) <= 60
    dices = [random.randint(1, 6) for _ in range(3)]
    total = sum(dices)
    res_text = "tai" if total >= 11 else "xiu"

    if is_rigged and res_text == side:
        if side == "tai": dices = [random.randint(1, 3) for _ in range(3)]
        else: dices = [random.randint(4, 6) for _ in range(3)]
        total = sum(dices)
        res_text = "tai" if total >= 11 else "xiu"

    # Lưu cầu kèm giá trị số nút
    history_cau.append({"res": "T" if res_text == "tai" else "X", "val": total})
    if len(history_cau) > 10: history_cau.pop(0)

    win = (side == res_text)
    if win: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount * 2, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, 'TAI_XIU', ?, ?, 0, ?)", 
             (ctx.author.id, amount, side.upper(), "WIN" if win else "LOSE"))

    embed = discord.Embed(title=f"🎲 KẾT QUẢ: {res_text.upper()} ({total})", color=0x00ff00 if win else 0xff0000)
    embed.description = f"Xúc xắc: `{dices[0]} {dices[1]} {dices[2]}`\nBạn đã **{'THẮNG' if win else 'THUA'}** `{amount:,}` Cash"
    await msg.edit(content=None, embed=embed)

@bot.command()
async def cau(ctx):
    if not history_cau: return await ctx.send("📑 Chưa có dữ liệu cầu.")
    
    # Vẽ biểu đồ ASCII lên xuống theo số nút
    chart = ""
    for entry in history_cau:
        val = entry['val']
        # Biểu diễn độ cao thấp của nút bằng các vạch
        bar = "┃" + "█" * (val // 2) + f" ({val})"
        chart += f"{entry['res']} {bar}\n"
    
    embed = discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU TÀI XỈU", color=0xe74c3c)
    embed.description = f"```\n{chart}\n```\n*Cầu hiển thị 10 ván gần nhất (T/X và tổng số nút)*"
    await ctx.send(embed=embed)

# ================= 3. BXH & VÍ & SHOP =================
@tasks.loop(minutes=20)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    total_users = query_db("SELECT COUNT(*) FROM users", one=True)[0]
    
    embed = discord.Embed(title="✨ BẢNG VÀNG ĐẠI GIA VERDICT CASH ✨", color=0xffd700)
    embed.description = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    lb_text = ""
    for i, (u_id, coins) in enumerate(top):
        m = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, "🔹")
        lb_text += f"{m} **Top {i+1}** | <@{u_id}>\n┗━━━ Tài sản: `{coins:,.0f}` Cash\n\n"
    
    embed.add_field(name="🏆 DANH SÁCH CAO THỦ", value=lb_text or "Chưa có dữ liệu", inline=False)
    embed.add_field(name="📊 THÔNG SỐ", value=f"👤 Dân chơi: `{total_users}` | 📅 <t:{int(datetime.now().timestamp())}:R>", inline=False)
    
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", color=0x2ecc71)
    embed.description = f"👤 **Người sở hữu:** {ctx.author.mention}\n💰 **Số dư:** `{coins:,.0f}` Verdict Cash"
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp `{amount:,}` cho {member.mention}")

@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    if match_id not in current_matches: return await ctx.send("❌ Mã trận không tồn tại!")
    # ... (Giữ logic trừ tiền và gửi DM như bản trước) ...
    await ctx.send("✅ Đã chốt kèo! Kiểm tra DM nhận vé.")
    try:
        e = discord.Embed(title="🎟️ VÉ CƯỢC VERDICT", color=0x3498db)
        e.add_field(name="🏟️ Trận ID", value=f"`{match_id}`", inline=True)
        e.add_field(name="💰 Tiền", value=f"`{amount:,}`", inline=True)
        await ctx.author.send(embed=e)
    except: pass

# ================= KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    if not auto_update_matches.is_running(): auto_update_matches.start()
    if not update_leaderboard.is_running(): update_leaderboard.start()
    print("🚀 Bot đã online!")

bot.run(TOKEN)
