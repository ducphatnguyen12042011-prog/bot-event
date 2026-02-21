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

# ================= 🎲 MINI GAME TÀI XỈU (48% WIN - SOI CẦU) =================

class TaiXiuView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.history = [random.choice(["Tài", "Xỉu"]) for _ in range(10)]

    @ui.button(label="🔴 TÀI", style=discord.ButtonStyle.danger)
    async def tai(self, i, b): await i.response.send_modal(TaiXiuMiniModal("Tài", self))

    @ui.button(label="🔵 XỈU", style=discord.ButtonStyle.primary)
    async def xiu(self, i, b): await i.response.send_modal(TaiXiuMiniModal("Xỉu", self))

    @ui.button(label="🔍 SOI CẦU MINI", style=discord.ButtonStyle.secondary)
    async def soi_cau(self, i, b):
        cau_str = " -> ".join([f"`{x}`" for x in self.history])
        tip = random.choice(["Cầu đang bệt!", "Cầu 1-1 rõ rệt.", "Tài đang vượng.", "Sắp đảo cầu rồi!"])
        emb = discord.Embed(title="📊 LỊCH SỬ CẦU MINI", description=cau_str, color=0x9b59b6)
        emb.add_field(name="💡 Gợi ý", value=tip)
        await i.response.send_message(embed=emb, ephemeral=True)

class TaiXiuMiniModal(ui.Modal, title='🎲 ĐẶT CƯỢC TÀI XỈU MINI'):
    amt = ui.TextInput(label='Số tiền cược (Cash)', placeholder='Tối thiểu 1,000...')

    def __init__(self, choice, parent_view):
        super().__init__()
        self.choice, self.parent_view = choice, parent_view

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Không đủ Cash!", ephemeral=True)

            is_win = random.randint(1, 100) <= 48
            dice = [random.randint(1, 6) for _ in range(3)]
            total = sum(dice)
            real_res = self.choice if is_win else ("Xỉu" if self.choice == "Tài" else "Tài")
            
            self.parent_view.history.append(real_res)
            if len(self.parent_view.history) > 10: self.parent_view.history.pop(0)

            if is_win:
                query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, i.user.id))
                res_msg, color = f"🎉 THẮNG! +{val:,}", 0x2ecc71
            else:
                query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
                res_msg, color = f"💀 THUA! -{val:,}", 0xe74c3c

            emb = discord.Embed(title=res_msg, description=f"Kết quả: **{real_res}** ({total})\nXúc xắc: ` {dice[0]} | {dice[1]} | {dice[2]} `", color=color)
            await i.response.send_message(embed=emb)
        except: await i.response.send_message("❌ Nhập số tiền hợp lệ!", ephemeral=True)

# ================= 🛒 SHOP & HÓA ĐƠN DM =================

class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)

    @ui.select(placeholder="Chọn vật phẩm mua...", options=[
        discord.SelectOption(label="Danh hiệu: Đại Gia", value="daigia", description="5,000,000 Cash", emoji="💎"),
        discord.SelectOption(label="Danh hiệu: Thần Bài", value="thanbai", description="2,000,000 Cash", emoji="🃏")
    ])
    async def callback(self, i: discord.Interaction, select: ui.Select):
        prices = {"daigia": 5000000, "thanbai": 2000000}
        cost = prices.get(select.values[0])
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        
        if not u or u['coins'] < cost: return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, i.user.id))
        await i.response.send_message("✅ Đã mua! Hóa đơn đã gửi vào DM.", ephemeral=True)

        try:
            emb = discord.Embed(title="🧾 HÓA ĐƠN VERDICT", color=0x2ecc71, timestamp=datetime.now())
            emb.add_field(name="Sản phẩm", value=select.values[0], inline=False)
            emb.add_field(name="Giá", value=f"{cost:,} Cash", inline=True)
            await i.user.send(embed=emb)
        except: pass

# ================= 🏟️ CƯỢC & LIVE Scoreboard =================

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, can_bet=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not can_bet: self.clear_items()

    @ui.button(label="🏠 Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b):
        if (parse_utc(self.m['utcDate']) - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['name'], self.hcap))

    @ui.button(label="✈️ Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b):
        if (parse_utc(self.m['utcDate']) - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['name'], -self.hcap))

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "tai", "Tài", self.ou))

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "xiu", "Xỉu", self.ou))

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Tiền cược', placeholder='Tối thiểu 10,000...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        val = int(self.amt.value)
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        if not u or u['coins'] < val: return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
        query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (i.user.id, self.m_id, self.side, val, self.line))
        await i.response.send_message(f"✅ Đã cược `{val:,}` cho {self.team}", ephemeral=True)

# ================= 🔄 LOOP HỆ THỐNG =================

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc, ch_live = bot.get_channel(ID_KENH_CUOC), bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc or not ch_live: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        filtered = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES]

        # 1. Kênh Cược
        await ch_cuoc.purge(limit=15, check=lambda m: m.author == bot.user)
        for m in [x for x in filtered if x['status'] == "TIMED"][:10]:
            h, o = get_smart_hcap(m), get_ou_line(m['homeTeam']['id'], m['awayTeam']['id'])
            emb = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x3498db)
            emb.description = f"🕒 Giờ đá: **{vn_time(m['utcDate'])}**\n━━━━━━━━━━━━\n⚖️ Chấp: `{h:+0.2g}` | ⚽ T/X: `{o}`"
            await ch_cuoc.send(embed=emb, view=MatchControlView(m, h, o, True))

        # 2. Kênh Live Xịn
        await ch_live.purge(limit=15, check=lambda m: m.author == bot.user)
        for m in [x for x in filtered if x['status'] in ["IN_PLAY", "LIVE", "PAUSED"]]:
            st = "☕ GIẢI LAO" if m['status'] == "PAUSED" else "⚽ LIVE"
            sc = m['score']
            ht = f"({sc['halfTime']['home']}-{sc['halfTime']['away']})" if sc['halfTime']['home'] is not None else ""
            emb = discord.Embed(title=f"🔴 {st}: {m['competition']['name']}", color=0xe74c3c)
            emb.add_field(name="Tỷ số", value=f"🏠 **{m['homeTeam']['shortName']}** `{sc['fullTime']['home']}` - `{sc['fullTime']['away']}` **{m['awayTeam']['shortName']}**\n*HT: {ht}*")
            await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, False))
    except: pass

@tasks.loop(minutes=10)
async def auto_settle_bets():
    pending = query_db("SELECT DISTINCT match_id FROM bets WHERE status = 'PENDING'")
    if not pending: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers={"X-Auth-Token": API_KEY}).json()
        finished = {m['id']: m for m in res.get('matches', [])}
        for row in pending:
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

# ================= ⚙️ COMMANDS =================

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Nạp `{amt:,}` Cash cho {user.mention}")

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{u['coins'] if u else 0:,}** Cash")

@bot.command()
async def shop(ctx):
    await ctx.send(embed=discord.Embed(title="🛒 SHOP VERDICT", color=0x3498db), view=ShopView())

@bot.command()
async def taixiu(ctx):
    await ctx.send(embed=discord.Embed(title="🎲 TÀI XỈU MINI", color=0xf1c40f), view=TaiXiuView())

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    auto_settle_bets.start()
    print(f"🚀 {bot.user.name} Online!")

bot.run(TOKEN)
