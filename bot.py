import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- 1. CẤU HÌNH HỆ THỐNG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_CUOC = 1474793205299155135
ID_KENH_LIVE = 1474672512708247582
ALLOWED_LEAGUES = ['PL', 'PD', 'CL']

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- 2. DATABASE ---
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

# --- 3. HỖ TRỢ LOGIC ---
def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

def get_smart_hcap(m):
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{m['competition']['code']}/standings"
        res = requests.get(url, headers=headers, timeout=5).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        diff = ranks.get(m['awayTeam']['id'], 10) - ranks.get(m['homeTeam']['id'], 10)
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.5

def get_ou_line(home_id, away_id):
    try:
        headers = {"X-Auth-Token": API_KEY}
        h_res = requests.get(f"https://api.football-data.org/v4/teams/{home_id}/matches?status=FINISHED&limit=5", headers=headers).json()
        a_res = requests.get(f"https://api.football-data.org/v4/teams/{away_id}/matches?status=FINISHED&limit=5", headers=headers).json()
        all_m = h_res.get('matches', []) + a_res.get('matches', [])
        if not all_m: return 2.5
        avg = sum((x['score']['fullTime']['home'] + x['score']['fullTime']['away']) for x in all_m) / len(all_m)
        return round(avg * 2) / 2 if avg > 0 else 2.5
    except: return 2.5

# ================= 🛒 HỆ THỐNG SHOP & HÓA ĐƠN =================

class ShopView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.select(placeholder="Chọn vật phẩm muốn mua...", options=[
        discord.SelectOption(label="Danh hiệu: Đại Gia", value="daigia", description="5,000,000 Cash", emoji="💎"),
        discord.SelectOption(label="Danh hiệu: Thần Bài", value="thanbai", description="2,000,000 Cash", emoji="🃏"),
        discord.SelectOption(label="Gói VIP 30 Ngày", value="vip_30", description="1,000,000 Cash", emoji="🌟")
    ])
    async def callback(self, i: discord.Interaction, select: ui.Select):
        prices = {"daigia": 5000000, "thanbai": 2000000, "vip_30": 1000000}
        item_id = select.values[0]
        cost = prices.get(item_id)
        item_name = [o.label for o in select.options if o.value == item_id][0]

        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        if not u or u['coins'] < cost:
            return await i.response.send_message(f"❌ Bạn không đủ tiền! Cần {cost:,} Cash.", ephemeral=True)

        # Trừ tiền
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, i.user.id))
        
        await i.response.send_message(f"✅ Giao dịch thành công! Hóa đơn đã được gửi vào DM.", ephemeral=True)

        # Gửi hóa đơn vào DM
        try:
            embed_bill = discord.Embed(title="🧾 HÓA ĐƠN THANH TOÁN", color=0x2ecc71, timestamp=datetime.now())
            embed_bill.add_field(name="Sản phẩm", value=f"**{item_name}**", inline=False)
            embed_bill.add_field(name="Chi phí", value=f"`{cost:,}` Cash", inline=True)
            embed_bill.add_field(name="Số dư còn lại", value=f"`{u['coins'] - cost:,}` Cash", inline=True)
            embed_bill.set_footer(text="Cảm ơn bạn đã mua hàng!")
            await i.user.send(embed=embed_bill)
        except:
            await i.followup.send("⚠️ Không thể gửi DM hóa đơn. Hãy mở DM để nhận biên lai lần sau!", ephemeral=True)

# ================= 🏟️ INTERFACE CƯỢC & LIVE =================

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, is_betting_channel=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not is_betting_channel: self.clear_items()

    def is_locked(self):
        start_time = parse_utc(self.m['utcDate'])
        return (start_time - datetime.now(timezone.utc)).total_seconds() < 300

    async def handle_bet(self, i, side, team, line):
        if self.is_locked():
            return await i.response.send_message("❌ Trận đấu đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], side, team, line))

    @ui.button(label="🏠 Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b): await self.handle_bet(i, "chu", self.m['homeTeam']['name'], self.hcap)

    @ui.button(label="✈️ Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b): await self.handle_bet(i, "khach", self.m['awayTeam']['name'], -self.hcap)

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await self.handle_bet(i, "tai", "Tài", self.ou)

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await self.handle_bet(i, "xiu", "Xỉu", self.ou)

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Tối thiểu 10,000...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000: return await i.response.send_message("❌ Cược tối thiểu 10,000!", ephemeral=True)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (i.user.id, self.m_id, self.side, val, self.line))
            await i.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}**!", ephemeral=True)
        except: await i.response.send_message("❌ Lỗi dữ liệu!", ephemeral=True)

# ================= 🔄 LOOP HỆ THỐNG & TRẢ THƯỞNG =================

@tasks.loop(minutes=10)
async def auto_settle_bets():
    pending_bets = query_db("SELECT DISTINCT match_id FROM bets WHERE status = 'PENDING'")
    if not pending_bets: return
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers=headers).json()
        finished = {m['id']: m for m in res.get('matches', [])}
        for row in pending_bets:
            m_id = row['match_id']
            if m_id in finished:
                m = finished[m_id]
                h, a = m['score']['fullTime']['home'], m['score']['fullTime']['away']
                bets = query_db("SELECT * FROM bets WHERE match_id = ? AND status = 'PENDING'", (m_id,))
                for b in bets:
                    win = False
                    if b['side'] == 'chu' and (h + b['handicap']) > a: win = True
                    elif b['side'] == 'khach' and (a + b['handicap']) > h: win = True
                    elif b['side'] == 'tai' and (h + a) > b['handicap']: win = True
                    elif b['side'] == 'xiu' and (h + a) < b['handicap']: win = True
                    
                    if win:
                        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(b['amount']*1.9), b['user_id']))
                        query_db("UPDATE bets SET status = 'WIN' WHERE id = ?", (b['id'],))
                    else:
                        query_db("UPDATE bets SET status = 'LOSS' WHERE id = ?", (b['id'],))
    except: pass

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc or not ch_live: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        filtered = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES]

        # Kênh Cược
        await ch_cuoc.purge(limit=20, check=lambda m: m.author == bot.user)
        for m in [x for x in filtered if x['status'] == "TIMED"][:10]:
            h, o = get_smart_hcap(m), get_ou_line(m['homeTeam']['id'], m['awayTeam']['id'])
            emb = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x3498db)
            emb.description = f"🕒 Giờ đá: **{vn_time(m['utcDate'])}**\n━━━━━━━━━━━━\n⚖️ **Chấp**: `{h:+0.2g}` | ⚽ **T/X**: `{o}`"
            await ch_cuoc.send(embed=emb, view=MatchControlView(m, h, o, True))

        # Kênh Live (Giao diện mới)
        await ch_live.purge(limit=20, check=lambda m: m.author == bot.user)
        live = [m for m in filtered if m['status'] in ["IN_PLAY", "LIVE", "PAUSED"]]
        for m in live:
            st = "☕ ĐANG GIẢI LAO" if m['status'] == "PAUSED" else "⚽ ĐANG THI ĐẤU"
            sc = m['score']
            ht = f"({sc['halfTime']['home']} - {sc['halfTime']['away']})" if sc['halfTime']['home'] is not None else ""
            emb = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
            emb.add_field(name=st, value=f"🏠 **{m['homeTeam']['shortName']}** ` {sc['fullTime']['home']} ` — ` {sc['fullTime']['away']} ` **{m['awayTeam']['shortName']}**\n*Hiệp 1: {ht}*", inline=False)
            emb.set_footer(text=f"Cập nhật: {datetime.now().strftime('%H:%M:%S')}")
            await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, False))
    except: pass

# ================= ⚙️ COMMANDS =================

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{u['coins'] if u else 0:,}** Cash")

@bot.command()
async def shop(ctx):
    await ctx.send(embed=discord.Embed(title="🛒 SHOP VERDICT", description="Chọn vật phẩm bên dưới để mua!", color=0x3498db), view=ShopView())

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    auto_settle_bets.start()
    print(f"🚀 {bot.user.name} đã sẵn sàng!")

bot.run(TOKEN)
