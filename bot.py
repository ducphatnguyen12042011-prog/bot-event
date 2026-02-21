import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- CẤU HÌNH HỆ THỐNG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582 # Channel Kèo & Tỉ số
ID_BXH = 1474674662792232981     # Channel BXH Đại Gia
ALLOWED_LEAGUES = ['PL', 'PD', 'CL'] # Ngoại hạng Anh, La Liga, Cúp C1

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('verdict_pro.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        return (res[0] if res and one else res)
    finally:
        conn.close()

# --- LOGIC KÈO CHẤP & THỜI GIAN ---
def get_smart_hcap(m):
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{m['competition']['code']}/standings"
        res = requests.get(url, headers=headers, timeout=5).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        # Công thức: Chênh 4 bậc hạng chấp 0.25 trái
        h_rank = ranks.get(m['homeTeam']['id'], 10)
        a_rank = ranks.get(m['awayTeam']['id'], 10)
        diff = a_rank - h_rank
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.0

def vn_time(utc_str):
    dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

# ================= 🎫 HỆ THỐNG CƯỢC & DM VÉ =================
class BetModal(ui.Modal, title='🎰 XÁC NHẬN CƯỢC VERDICT'):
    amt = ui.TextInput(label='Số tiền cược (Verdict Cash)', placeholder='Ví dụ: 50000', min_length=1)
    
    def __init__(self, m_id, side, team, hcap):
        super().__init__(); self.m_id=m_id; self.side=side; self.team=team; self.hcap=hcap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not u or u['coins'] < val: 
                return await interaction.response.send_message("❌ Bạn không đủ Cash để thực hiện giao dịch!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')",
                     (interaction.user.id, self.m_id, self.side, val, self.hcap))
            
            # Gửi vé qua DM
            embed = discord.Embed(title="🎫 VÉ CƯỢC HỆ THỐNG", color=0x2ecc71, timestamp=datetime.now())
            embed.description = (f"👤 **Người cược**: {interaction.user.mention}\n"
                                 f"🏟️ **Trận đấu**: {self.team}\n"
                                 f"⚖️ **Kèo chấp**: `{self.hcap:+0.2g}`\n"
                                 f"💰 **Tiền cược**: `{val:,}` Cash\n\n"
                                 f"*Hệ thống sẽ tự động trả thưởng khi trận đấu kết thúc.*")
            try: await interaction.user.send(embed=embed)
            except: pass
            
            await interaction.response.send_message(f"✅ Đã đặt cược thành công! Vé đã được gửi vào DM.", ephemeral=True)
        except: await interaction.response.send_message("❌ Lỗi: Vui lòng nhập số tiền hợp lệ.", ephemeral=True)

# ================= 🎲 TÀI XỈU 53% THUA & SOI CẦU =================
tx_history = []

@bot.command()
async def taixiu(ctx, side: str, amt: int):
    global tx_history
    side = side.lower()
    if side not in ['tai', 'xiu'] or amt <= 0: return await ctx.send("Sử dụng: `!taixiu <tai/xiu> <tiền>`")
    
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not u or u['coins'] < amt: return await ctx.send("❌ Bạn không đủ Cash!")

    # Logic 53% Thua
    is_win = random.random() < 0.47 
    dice = [random.randint(1,6) for _ in range(3)]
    total = sum(dice)
    res = "tai" if total >= 11 else "xiu"

    if (is_win and res != side) or (not is_win and res == side):
        total = random.randint(11,17) if side == "tai" and is_win else random.randint(4,10)
        res = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt if side==res else -amt, ctx.author.id))
    tx_history.append(total)
    
    emb = discord.Embed(title="🎲 VERDICT TÀI XỈU", color=0x2ecc71 if side==res else 0xe74c3c)
    emb.description = f"Kết quả: **{total}** ({res.upper()})\nBạn: **{'THẮNG' if side==res else 'THUA'}** `{amt:,}` Cash"
    await ctx.send(embed=emb)

@bot.command()
async def cau(ctx):
    pts = tx_history[-15:]
    if not pts: return await ctx.send("Chưa có dữ liệu cầu.")
    graph = "```\n" + "\n".join([f"{l:02}| " + "".join(["● " if p==l else "──" for p in pts]) for l in range(18, 2, -1)]) + "\n    " + "--"*len(pts) + "```"
    await ctx.send(embed=discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU (15 Phiên)", description=graph, color=0x3498db))

# ================= 🛒 SHOP TICKET (TỰ ĐỔI TÊN) =================
class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    async def buy(self, interaction, item, price):
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not u or u['coins'] < price: return await interaction.response.send_message("❌ Không đủ Cash!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        cat = discord.utils.get(interaction.guild.categories, name="TICKETS")
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), 
                      interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        channel = await interaction.guild.create_text_channel(name=f"🛒-{item}", category=cat, overwrites=overwrites)
        await channel.send(f"📦 {interaction.user.mention} mua **{item}**. Vui lòng chờ Admin!")
        await interaction.response.send_message(f"✅ Đã tạo Ticket: {channel.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.success)
    async def b1(self, i, b): await self.buy(i, "The-Doi-Ten", 50000)
    @ui.button(label="Role VIP (200k)", style=discord.ButtonStyle.primary)
    async def b2(self, i, b): await self.buy(i, "Role-VIP", 200000)

# ================= 🏟️ SCOREBOARD & TRẢ THƯỞNG =================
@tasks.loop(minutes=3)
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
            is_locked = m['status'] != "TIMED"
            
            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x2b2d31)
            embed.description = (f"⏰ Khởi tranh: `{vn_time(m['utcDate'])}` VN\n\n"
                                 f"🏠 **{m['homeTeam']['name']}**\n╰ Tỉ số: `{m['score']['fullTime']['home'] or 0}` — Chấp: `{hcap:+0.2g}`\n\n"
                                 f"✈️ **{m['awayTeam']['name']}**\n╰ Tỉ số: `{m['score']['fullTime']['away'] or 0}`\n"
                                 f"━━━━━━━━━━━━━━━━━━━━\n"
                                 f"📢 Trạng thái: **{m['status']}**")

            class BetBtns(ui.View):
                @ui.button(label=f"Cược {m['homeTeam']['shortName']}", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def c1(self, i, b): await i.response.send_modal(BetModal(m['id'], "chu", m['homeTeam']['name'], hcap))
                @ui.button(label=f"Cược {m['awayTeam']['shortName']}", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def c2(self, i, b): await i.response.send_modal(BetModal(m['id'], "khach", m['awayTeam']['name'], -hcap))
            
            await ch.send(embed=embed, view=BetBtns() if not is_locked else None)
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
                if res > 0: # Thắng (Trả x1.95)
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(b['amount']*1.95), b['user_id']))
                elif res == 0: # Hòa kèo
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (b['amount'], b['user_id']))
                query_db("UPDATE bets SET status = 'DONE' WHERE id = ?", (b['id'],))
        except: continue

# ================= ✨ BXH ĐẠI GIA & VÍ =================
@tasks.loop(minutes=30)
async def update_bxh():
    ch = bot.get_channel(ID_BXH)
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=0xffd700, timestamp=datetime.now())
    medals = ["🥇", "🥈", "🥉", "👤", "👤", "👤", "👤", "👤", "👤", "👤"]
    desc = ""
    for i, r in enumerate(top):
        desc += f"{medals[i]} **Top {i+1}** <@{r['user_id']}> — `{r['coins']:,}` Cash\n"
    embed.description = desc or "Chưa có dữ liệu."
    await ch.purge(limit=2); await ch.send(embed=embed)

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = u['coins'] if u else 0
    view = ui.View()
    view.add_item(ui.Button(label="Shop Vật Phẩm", style=discord.ButtonStyle.success, custom_id="open_shop"))
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", description=f"Số dư của {ctx.author.mention}: **{coins:,}** Cash", color=0x2ecc71)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start(); auto_payout.start(); update_bxh.start()
    print("🚀 VERDICT FINAL SYSTEM READY!")

@bot.event
async def on_interaction(interaction):
    if interaction.type == discord.InteractionType.component:
        if interaction.data['custom_id'] == "open_shop":
            await interaction.response.send_message("Chào mừng tới Shop!", view=ShopView(), ephemeral=True)

bot.run(TOKEN)
