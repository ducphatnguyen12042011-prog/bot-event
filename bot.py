import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta
from dateutil import parser

# --- CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582 
ID_BXH = 1474674662792232981    
ALLOWED_LEAGUES = ['PL', 'PD', 'CL']

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('verdict_master.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        return (res[0] if res and one else res)
    finally:
        conn.close()

# --- HELPER FUNCTIONS ---
def get_match_minute(utc_date_str, status):
    if status != "IN_PLAY": return None
    try:
        start = parser.parse(utc_date_str)
        now = datetime.now(timezone.utc)
        minute = int((now - start).total_seconds() / 60)
        if minute < 1: return 1
        if 45 < minute < 50: return "45+"
        if minute > 90: return "90+"
        return minute
    except: return "?"

def get_smart_hcap(m):
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{m['competition']['code']}/standings"
        res = requests.get(url, headers=headers, timeout=5).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        diff = ranks.get(m['awayTeam']['id'], 10) - ranks.get(m['homeTeam']['id'], 10)
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.0

# ================= 🛒 HỆ THỐNG SHOP TICKET =================
class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    async def create_ticket(self, interaction, item, price):
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not u or u['coins'] < price:
            return await interaction.response.send_message("❌ Bạn không đủ Verdict Cash!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        cat = discord.utils.get(interaction.guild.categories, name="TICKETS")
        if not cat: return await interaction.response.send_message("❌ Lỗi: Server thiếu Category 'TICKETS'", ephemeral=True)
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        # Ticket đổi tên theo sản phẩm
        channel = await interaction.guild.create_text_channel(name=f"🛒-{item}", category=cat, overwrites=overwrites)
        await channel.send(f"📦 {interaction.user.mention} đã đổi **{item}**. Chờ Admin xử lý!")
        await interaction.response.send_message(f"✅ Đã tạo Ticket mua hàng: {channel.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.success, emoji="🏷️")
    async def b1(self, i, b): await self.create_ticket(i, "The-Doi-Ten", 50000)
    
    @ui.button(label="Role VIP (200k)", style=discord.ButtonStyle.primary, emoji="💎")
    async def b2(self, i, b): await self.create_ticket(i, "Role-VIP-7D", 200000)

# ================= 🎲 TÀI XỈU SOI CẦU (53% THUA) =================
tx_history = []

@bot.command()
async def taixiu(ctx, side: str, amt: int):
    global tx_history
    side = side.lower()
    if side not in ['tai', 'xiu'] or amt <= 0: return await ctx.send("Sử dụng: `!taixiu <tai/xiu> <tiền>`")
    
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not u or u['coins'] < amt: return await ctx.send("❌ Bạn không đủ Verdict Cash!")

    is_win = random.random() < 0.47 # Nhà cái thắng 53%
    dice = [random.randint(1,6) for _ in range(3)]
    total = sum(dice)
    res = "tai" if total >= 11 else "xiu"

    if (is_win and res != side) or (not is_win and res == side):
        total = random.randint(11,17) if side == "tai" and is_win else random.randint(4,10)
        res = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt if side==res else -amt, ctx.author.id))
    tx_history.append(total)
    
    color = 0x2ecc71 if side == res else 0xe74c3c
    emb = discord.Embed(title="🎲 KẾT QUẢ TÀI XỈU", color=color)
    emb.description = f"Kết quả: **{total}** ({res.upper()})\nBạn: **{'THẮNG' if side==res else 'THUA'}** `{amt:,}` Cash"
    await ctx.send(embed=emb)

@bot.command()
async def cau(ctx):
    pts = tx_history[-15:]
    if not pts: return await ctx.send("Chưa có dữ liệu cầu!")
    graph = "```\n" + "\n".join([f"{l:02}| " + "".join(["● " if p==l else "──" for p in pts]) for l in range(18, 2, -1)]) + "```"
    await ctx.send(embed=discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU VERDICT", description=graph, color=0x3498db))

# ================= 🏟️ SCOREBOARD (PHÚT ĐÁ & TRẢ THƯỞNG) =================
@tasks.loop(minutes=2)
async def update_scoreboard():
    ch = bot.get_channel(ID_BONG_DA)
    if not ch: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = [m for m in res.get('matches', []) if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "TIMED", "PAUSED", "LIVE"]][:5]
        
        await ch.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in matches:
            hcap = get_smart_hcap(m)
            min_now = get_match_minute(m['utcDate'], m['status'])
            status_txt = f"🔴 ĐANG ĐÁ: Phút {min_now}'" if m['status'] == "IN_PLAY" else "🕒 SẮP DIỄN RA"
            if m['status'] == "PAUSED": status_txt = "☕ NGHỈ HIỆP"

            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x2b2d31)
            embed.description = (f"**{status_txt}**\n"
                                 f"━━━━━━━━━━━━━━━━━━━━\n"
                                 f"🏠 **{m['homeTeam']['name']}**\n╰ Tỉ số: `{m['score']['fullTime']['home'] or 0}` — Chấp: `{hcap:+0.2g}`\n\n"
                                 f"✈️ **{m['awayTeam']['name']}**\n╰ Tỉ số: `{m['score']['fullTime']['away'] or 0}` — Kèo: `0` (Ăn đủ)\n"
                                 f"━━━━━━━━━━━━━━━━━━━━\n"
                                 f"📢 ID Trận: {m['id']}")

            class BetBtns(ui.View):
                @ui.button(label=f"Cược {m['homeTeam']['shortName']}", style=discord.ButtonStyle.primary, disabled=(m['status'] != "TIMED"))
                async def c1(self, i, b): await i.response.send_modal(BetModal(m['id'], "chu", m['homeTeam']['name'], hcap))
                @ui.button(label=f"Cược {m['awayTeam']['shortName']}", style=discord.ButtonStyle.danger, disabled=(m['status'] != "TIMED"))
                async def c2(self, i, b): await i.response.send_modal(BetModal(m['id'], "khach", m['awayTeam']['name'], -hcap))
            
            await ch.send(embed=embed, view=BetBtns() if m['status'] == "TIMED" else None)
    except: pass

@tasks.loop(minutes=10)
async def auto_payout():
    pending = query_db("SELECT * FROM bets WHERE status = 'PENDING'")
    if not pending: return
    headers = {"X-Auth-Token": API_KEY}
    for b in pending:
        try:
            r = requests.get(f"https://api.football-data.org/v4/matches/{b['match_id']}", headers=headers).json()
            if r.get('status') == 'FINISHED':
                h, a = r['score']['fullTime']['home'], r['score']['fullTime']['away']
                res = (h + b['handicap'] - a) if b['side'] == "chu" else (a + b['handicap'] - h)
                if res > 0: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(b['amount']*1.95), b['user_id']))
                elif res == 0: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (b['amount'], b['user_id']))
                query_db("UPDATE bets SET status = 'DONE' WHERE id = ?", (b['id'],))
        except: continue

# ================= ✨ VÍ & BXH ĐẠI GIA =================
@tasks.loop(minutes=30)
async def update_bxh():
    ch = bot.get_channel(ID_BXH)
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=0xffd700, timestamp=datetime.now())
    medals = ["🥇", "🥈", "🥉", "👤", "👤", "👤", "👤", "👤", "👤", "👤"]
    embed.description = "\n".join([f"{medals[i]} **#{i+1}** <@{r['user_id']}> — `{r['coins']:,}` Cash" for i, r in enumerate(top)])
    await ch.purge(limit=2); await ch.send(embed=embed)

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    view = ui.View()
    view.add_item(ui.Button(label="Shop Vật Phẩm", style=discord.ButtonStyle.success, custom_id="shop_open"))
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", description=f"Số dư: **{u['coins'] if u else 0:,}** Cash", color=0x2ecc71)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

# ================= VẬN HÀNH =================
class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC HỆ THỐNG'):
    amt = ui.TextInput(label='Tiền cược', placeholder='Nhập số Cash...')
    def __init__(self, m_id, side, team, hcap):
        super().__init__(); self.m_id=m_id; self.side=side; self.team=team; self.hcap=hcap

    async def on_submit(self, interaction: discord.Interaction):
        val = int(self.amt.value)
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not u or u['coins'] < val: return await interaction.response.send_message("❌ Không đủ tiền!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (interaction.user.id, self.m_id, self.side, val, self.hcap))
        
        # Gửi vé qua DM
        emb = discord.Embed(title="✅ XÁC NHẬN VÉ CƯỢC", color=0x2ecc71)
        emb.description = f"🏟️ **Trận**: {self.team}\n⚖️ **Kèo**: `{self.hcap:+}`\n💰 **Cược**: `{val:,}` Cash"
        try: await interaction.user.send(embed=emb)
        except: pass
        await interaction.response.send_message("✅ Đã đặt cược & gửi vé vào DM!", ephemeral=True)

@bot.event
async def on_interaction(interaction):
    if interaction.type == discord.InteractionType.component and interaction.data['custom_id'] == "shop_open":
        await interaction.response.send_message("🛒 **CỬA HÀNG VERDICT CASH**", view=ShopView(), ephemeral=True)

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start(); auto_payout.start(); update_bxh.start()
    print("🚀 MASTER BOT IS ONLINE!")

bot.run(TOKEN)
