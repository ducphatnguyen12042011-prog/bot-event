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

# ================= DATABASE & BIẾN TOÀN CỤC =================
history_cau = [] # Lưu lịch sử Tài Xỉu
current_matches = {}

def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ================= SHOP DATA =================
SHOP_ITEMS = {
    "1": {"name": "Danh hiệu: Đại Gia", "price": 50000, "role": 12345},
    "2": {"name": "Thẻ Đổi Màu Tên", "price": 20000, "role": None}
}

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
            return await interaction.response.send_message("📭 Chưa có giao dịch nào.", ephemeral=True)
        
        embed = discord.Embed(title="📜 LỊCH SỬ GIAO DỊCH", color=0x3498db)
        desc = ""
        for team, amt, status in history:
            icon = "✅" if "WIN" in status or "DONE" in status else ("⏳" if "PENDING" in status else "❌")
            desc += f"{icon} **{team}** | Tiền: `{amt:,}` | KQ: `{status}`\n"
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= 1. GIAO DIỆN BÓNG ĐÁ ĐỐI XỨNG =================
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
            h_name, a_name = m['homeTeam']['shortName'] or m['homeTeam']['name'], m['awayTeam']['shortName'] or m['awayTeam']['name']
            h_icon, a_icon = m['homeTeam'].get('crest'), m['awayTeam'].get('crest')
            h_score = m['score']['fullTime']['home'] or 0
            a_score = m['score']['fullTime']['away'] or 0
            start_dt = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ')

            embed = discord.Embed(title=f"⚽  {h_score}  —  {a_score}  ⚽", color=0x2b2d31)
            embed.set_author(name=f"{h_name}", icon_url=h_icon)
            embed.set_thumbnail(url=a_icon)
            
            embed.add_field(name=f"🏠 {h_name}", value="`Chủ nhà`", inline=True)
            embed.add_field(name=f"✈️ {a_name}", value="`Sân khách`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name=f"Đội A: {h_name}", value="**- 0.5**", inline=True)
            embed.add_field(name=f"Đội B: {a_name}", value="**+ 0.5**", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name="⏰ Thời gian", value=f"<t:{int(start_dt.timestamp())}:R>", inline=True)
            embed.add_field(name="🆔 Mã trận", value=f"`{mid}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.set_footer(text=f"!cuoc {mid} <chu/khach> <tiền>")
            await channel.send(embed=embed)
    except: pass

# ================= 2. TÀI XỈU 60% & SOI CẦU =================
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
    res = "tai" if total >= 11 else "xiu"

    if is_rigged and res == side:
        if side == "tai": dices = [random.randint(1, 3) for _ in range(3)]
        else: dices = [random.randint(4, 6) for _ in range(3)]
        total = sum(dices)
        res = "tai" if total >= 11 else "xiu"

    history_cau.append("T" if res == "tai" else "X")
    if len(history_cau) > 10: history_cau.pop(0)

    win = (side == res)
    if win: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount * 2, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, 'TAI_XIU', ?, ?, 0, ?)", 
             (ctx.author.id, amount, side.upper(), "WIN" if win else "LOSE"))

    embed = discord.Embed(title=f"🎲 KẾT QUẢ: {res.upper()} ({total})", color=0x00ff00 if win else 0xff0000)
    embed.description = f"Xúc xắc: `{dices[0]} {dices[1]} {dices[2]}`\nBạn đã **{'THẮNG' if win else 'THUA'}** `{amount:,}` Cash"
    embed.set_footer(text=f"Cầu: {'-'.join(history_cau)}")
    await msg.edit(content=None, embed=embed)

@bot.command()
async def cau(ctx):
    if not history_cau: return await ctx.send("📑 Chưa có dữ liệu cầu.")
    embed = discord.Embed(title="📊 BẢNG SOI CẦU TÀI XỈU", description=f"➡️ {' '.join([f'**[{c}]**' for c in history_cau])}", color=0xe74c3c)
    await ctx.send(embed=embed)

# ================= 3. ĐẶT CƯỢC & VÉ DM =================
@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    if match_id not in current_matches: return await ctx.send("❌ Mã trận sai!")
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Không đủ tiền!")

    match = current_matches[match_id]
    team_bet = match['homeTeam']['name'] if side.lower() in ["chu", "home"] else match['awayTeam']['name']
    
    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, ?, ?, ?, 0.5, 'PENDING')", 
             (ctx.author.id, match_id, amount, team_bet))

    await ctx.send("✅ Đã chốt kèo! Kiểm tra DM.")
    try:
        e = discord.Embed(title="🎟️ VÉ CƯỢC VERDICT", color=0x3498db)
        e.add_field(name="🏟️ Trận", value=f"{match['homeTeam']['name']} vs {match['awayTeam']['name']}", inline=False)
        e.add_field(name="🚩 Đặt cho", value=f"`{team_bet}`", inline=True)
        e.add_field(name="💰 Tiền", value=f"`{amount:,}`", inline=True)
        await ctx.author.send(embed=e)
    except: pass

# ================= 4. BXH & VÍ NÂNG CẤP =================
@tasks.loop(minutes=20)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    
    # Lấy Top 10 và tổng số người chơi từ database
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    total_users = query_db("SELECT COUNT(*) FROM users", one=True)[0]
    
    embed = discord.Embed(
        title="✨ BẢNG VÀNG ĐẠI GIA VERDICT CASH ✨",
        description=f"🏆 *Nơi vinh danh những triệu phú giàu nhất server*\n━━━━━━━━━━━━━━━━━━━━",
        color=0xffd700 # Màu vàng Gold sang trọng
    )

    if not top:
        embed.description = "Hiện tại chưa có dữ liệu đại gia."
    else:
        leaderboard_text = ""
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        
        for i, (u_id, coins) in enumerate(top):
            rank_icon = medals.get(i, "👤")
            # Hiển thị Top kèm định dạng tiền có dấu phẩy ngăn cách (1,000,000)
            leaderboard_text += f"{rank_icon} **Top {i+1}** | <@{u_id}>\n"
            leaderboard_text += f"┗━━💰 `{coins:,.0f}` Verdict Cash\n\n"
        
        embed.add_field(name="📊 Danh sách xếp hạng", value=leaderboard_text, inline=False)

    # Thêm thông số tổng quan hệ thống
    embed.add_field(
        name="🏁 Thông số", 
        value=f"👥 Tổng dân chơi: `{total_users}`\n📅 Cập nhật: <t:{int(datetime.now().timestamp())}:R>", 
        inline=False
    )
    
    embed.set_footer(text="Hãy tích cực soi cầu để ghi danh bảng vàng!")
    
    # Làm sạch kênh và gửi bảng mới
    await channel.purge(limit=5)
    await channel.send(embed=embed)

@bot.command()
async def vi(ctx):
    # Lấy số dư thực tế của người dùng
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    
    embed = discord.Embed(
        title="💳 VÍ VERDICT CASH", 
        description=f"Chào {ctx.author.mention}, số dư của bạn là:\n💰 **{coins:,.0f}** Verdict Cash", 
        color=0x2ecc71 # Màu xanh lá của tiền
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.set_footer(text="Bấm nút bên dưới để xem lịch sử giao dịch.")
    
    # Gửi kèm view chứa nút bấm lịch sử
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    e = discord.Embed(title="💳 VÍ VERDICT CASH", description=f"Số dư: **{coins:,}** Cash", color=0x2ecc71)
    await ctx.send(embed=e, view=WalletView(ctx.author.id))

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp {amount:,} cho {member.mention}")

@bot.command()
async def shop(ctx):
    e = discord.Embed(title="🏪 SHOP VERDICT", color=0x9b59b6)
    for k, v in SHOP_ITEMS.items():
        e.add_field(name=f"[{k}] {v['name']}", value=f"Giá: `{v['price']:,}`", inline=False)
    await ctx.send(embed=e)

# ================= KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    auto_update_matches.start()
    update_leaderboard.start()
    print("🚀 Bot Final đã sẵn sàng!")

bot.run(TOKEN)
