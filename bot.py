import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone

# --- CONFIG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BXH = 1474674662792232981         
ID_BONG_DA = 1474672512708247582     

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ENGINE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        if not res: return None
        return (res[0] if one else res)
    finally:
        conn.close()

# ================= 1. UI: SHOP & VÍ & LỊCH SỬ =================
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @ui.button(label="📜 Lịch Sử Cược", style=discord.ButtonStyle.secondary, emoji="📝")
    async def history(self, interaction: discord.Interaction, button: ui.Button):
        res = query_db("SELECT side, amount, status, handicap FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        if not res: return await interaction.response.send_message("✨ Bạn chưa có lịch sử cược nào!", ephemeral=True)
        
        embed = discord.Embed(title="📜 LỊCH SỬ CƯỢC GẦN ĐÂY", color=0x3498db)
        for row in res:
            status_emoji = "✅" if row['status'] == "WIN" else ("❌" if row['status'] == "LOSE" else "🤝")
            embed.add_field(
                name=f"{status_emoji} Cửa {row['side'].upper()} (Chấp {row['handicap']:+})",
                value=f"Tiền: `{row['amount']:,}` | Trạng thái: **{row['status']}**", 
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="🛒 Vào Shop", style=discord.ButtonStyle.primary, emoji="🛍️")
    async def shop_btn(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(title="🏪 VERDICT PREMIUM SHOP", description="Nâng cấp tài khoản của bạn bằng Cash!", color=0xe91e63)
        embed.add_field(name="💳 Thẻ Đổi Tên", value="Giá: `50,000` Cash\nLệnh: `!mua 1`", inline=True)
        embed.add_field(name="👑 Role VIP (7d)", value="Giá: `500,000` Cash\nLệnh: `!mua 2`", inline=True)
        embed.set_footer(text="Giao dịch tự động qua lệnh !mua")
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d['coins'] if d else 0
    embed = discord.Embed(title="💳 VÍ ĐIỆN TỬ VERDICT", color=0x2ecc71)
    embed.add_field(name="Chủ sở hữu", value=f"👤 {ctx.author.mention}", inline=True)
    embed.add_field(name="Số dư khả dụng", value=f"💰 **{coins:,}** Cash", inline=True)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.set_image(url="https://i.imgur.com/R9Uf6vO.png") # Thanh trang trí
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

# ================= 2. MODAL CƯỢC & LOGIC KÈO CHẤP AI =================
def get_ai_handicap(h_rank, a_rank):
    if not h_rank or not a_rank: return 0.0
    diff = a_rank - h_rank
    return round((diff / 2.5) * 0.25 * 4) / 4

class CuocModal(ui.Modal, title='🎰 PHIẾU CƯỢC TRỰC TUYẾN'):
    amount = ui.TextInput(label='Số tiền đặt cược', placeholder='Nhập số Cash (VD: 100000)')
    def __init__(self, match_id, side, team_name, hcap):
        super().__init__()
        self.m_id, self.side, self.team, self.hcap = match_id, side, team_name, hcap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt < 1000: return await interaction.response.send_message("❌ Tối thiểu cược 1,000 Cash!", ephemeral=True)
            
            user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not user or user['coins'] < amt: return await interaction.response.send_message("❌ Ví bạn không đủ tiền!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
                     (interaction.user.id, self.m_id, self.side, amt, self.hcap))

            # Vé cược DM siêu đẹp
            emb = discord.Embed(title="🎫 VÉ CƯỢC XÁC NHẬN", color=0xf1c40f)
            emb.add_field(name="🛡️ Đội", value=f"**{self.team}**", inline=True)
            emb.add_field(name="📊 Kèo", value=f"**{self.hcap:+}**", inline=True)
            emb.add_field(name="💰 Tiền", value=f"`{amt:,}`", inline=True)
            emb.set_footer(text=f"Mã trận: {self.m_id} | Chúc bạn may mắn!")
            
            await interaction.user.send(embed=emb)
            await interaction.response.send_message("✅ Đã xác nhận cược! Check DM để giữ vé.", ephemeral=True)
        except: await interaction.response.send_message("❌ Vui lòng nhập số tiền hợp lệ!", ephemeral=True)

# ================= 3. SCOREBOARD: GIAO DIỆN CHUẨN LOGO =================
@tasks.loop(minutes=2)
async def update_scoreboard():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        std = requests.get("https://api.football-data.org/v4/competitions/PL/standings", headers={"X-Auth-Token": API_KEY}).json()
        ranks = {s['team']['id']: s['position'] for s in std['standings'][0]['table']}
        
        matches = [m for m in res.get('matches', []) if m['status'] in ["IN_PLAY", "TIMED", "LIVE"]][:3]
        await channel.purge(limit=5, check=lambda m: m.author == bot.user)

        for m in matches:
            h_rank, a_rank = ranks.get(m['homeTeam']['id'], 10), ranks.get(m['awayTeam']['id'], 10)
            h_hcap = get_ai_handicap(h_rank, a_rank)
            
            diff = (datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds() / 60
            is_locked = m['status'] != "TIMED" or diff <= 15
            
            embed = discord.Embed(color=0x2b2d31)
            embed.set_author(name=f"🏆 {m['competition']['name']} • {m['status']}")
            # Layout Logo và Tên hàng dọc, Tỉ số ở giữa
            embed.add_field(name="🏠 Chủ Nhà", value=f"**{m['homeTeam']['shortName']}**\n(Kèo: {h_hcap:+})", inline=True)
            embed.add_field(name="VS", value=f"**{m['score']['fullTime']['home'] or 0} - {m['score']['fullTime']['away'] or 0}**", inline=True)
            embed.add_field(name="✈️ Đội Khách", value=f"**{m['awayTeam']['shortName']}**\n(Kèo: 0.0)", inline=True)
            
            if m['homeTeam'].get('crest'): embed.set_thumbnail(url=m['homeTeam'].get('crest'))
            
            class BetBtns(ui.View):
                @ui.button(label="Cược Chủ", style=discord.ButtonStyle.primary, emoji="🏠", disabled=is_locked)
                async def b1(self, i, b): await i.response.send_modal(CuocModal(m['id'], "chu", m['homeTeam']['shortName'], h_hcap))
                @ui.button(label="Cược Khách", style=discord.ButtonStyle.danger, emoji="✈️", disabled=is_locked)
                async def b2(self, i, b): await i.response.send_modal(CuocModal(m['id'], "khach", m['awayTeam']['shortName'], -h_hcap))

            await channel.send(embed=embed, view=BetBtns() if not is_locked else None)
    except Exception as e: print(f"Lỗi Scoreboard: {e}")

# ================= 4. TÀI XỈU 47% & SOI CẦU LƯỚI =================
history_points = []
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_points
    side = side.lower()
    if side not in ["tai", "xiu"] or amount < 1000: return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [tiền]` (Min 1,000)")
    
    user = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user or user['coins'] < amount: return await ctx.send("❌ Không đủ Cash!")

    is_win = random.randint(1, 100) <= 47 # Casino winrate
    d1, d2, d3 = [random.randint(1, 6) for _ in range(3)]
    total = d1+d2+d3
    res = "tai" if total >= 11 else "xiu"
    
    if (is_win and res != side) or (not is_win and res == side):
        total = random.randint(11,18) if side == "tai" and is_win else random.randint(3,10)
        d1 = random.randint(1, min(6, total-2)); d2 = random.randint(1, min(6, total-d1-1)); d3 = total-d1-d2
        res = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount if side == res else -amount, ctx.author.id))
    history_points.append(total)

    embed = discord.Embed(title="🎲 PHIÊN TÀI XỈU", color=0x2ecc71 if side == res else 0xff4d4d)
    embed.add_field(name="Kết Quả", value=f"**{d1} - {d2} - {d3}** ➔ **{total} ({res.upper()})**", inline=False)
    embed.add_field(name="Biến Động", value=f"{'+' if side == res else '-'}{amount:,} Cash", inline=True)
    embed.set_footer(text=f"Người chơi: {ctx.author.name}")
    await ctx.send(embed=embed)

@bot.command()
async def cau(ctx):
    pts = history_points[-18:]
    graph = "```\n"
    for lvl in range(18, 2, -3):
        graph += f"{lvl:02} ┃" + "".join([" ● " if abs(p-lvl) < 2 else " ── " for p in pts]) + "\n"
    graph += "   ┗" + "━━━" * len(pts) + "```"
    await ctx.send(embed=discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU LƯỚI", description=graph, color=0xf1c40f))

# ================= 5. SETTLEMENT & AUTO REWARD =================
@tasks.loop(minutes=10)
async def auto_reward():
    pending = query_db("SELECT id, user_id, match_id, side, amount, handicap FROM bets WHERE status = 'PENDING'")
    if not pending: return
    for b in pending:
        try:
            r = requests.get(f"https://api.football-data.org/v4/matches/{b['match_id']}", headers={"X-Auth-Token": API_KEY}).json()
            if r.get('status') == 'FINISHED':
                h, a = r['score']['fullTime']['home'], r['score']['fullTime']['away']
                # Tính điểm kèo chấp
                final_score = (h + b['handicap'] - a) if b['side'] == "chu" else (a + b['handicap'] - h)
                
                status = "WIN" if final_score > 0 else ("DRAW" if final_score == 0 else "LOSE")
                if status == "WIN": query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(b['amount'] * 1.95), b['user_id']))
                elif status == "DRAW": query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (b['amount'], b['user_id']))
                
                query_db("UPDATE bets SET status = ? WHERE id = ?", (status, b['id']))
                u = await bot.fetch_user(b['user_id'])
                await u.send(f"🎊 **KẾT QUẢ TRẬN {b['match_id']}**: Bạn đã **{status}**! Tiền đã được cập nhật vào ví.")
        except: continue

# ================= 6. KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start(); auto_reward.start()
    print(f"🚀 VERDICT SYSTEM PRO ONLINE - {bot.user.name}")

bot.run(TOKEN)
