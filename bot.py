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
ID_KENH_CUOC = 1474793205299155135  # Kênh chỉ hiện trận CHƯA ĐÁ (Còn cược)
ID_KENH_LIVE = 1474672512708247582  # Kênh chỉ hiện trận ĐANG ĐÁ (Khóa cược)
ALLOWED_LEAGUES = ['PL', 'PD', 'CL'] # Premier League, La Liga, Champions League

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

# --- HELPERS ---
def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

def get_smart_hcap(m):
    # Logic tính kèo chấp tự động (Ví dụ mặc định 0.5)
    return 0.5 

def get_ou_line(home_id, away_id):
    # Logic tính kèo Tài Xỉu (Ví dụ mặc định 2.5)
    return 2.5

# ================= 💰 HỆ THỐNG TỰ ĐỘNG TRẢ THƯỞNG (10 PHÚT/LẦN) =================

@tasks.loop(minutes=10)
async def auto_settle_bets():
    pending_matches = query_db("SELECT DISTINCT match_id FROM bets WHERE status = 'PENDING'")
    if not pending_matches: return

    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers=headers).json()
        finished_list = {m['id']: m for m in res.get('matches', [])}

        for row in pending_matches:
            m_id = row['match_id']
            if m_id in finished_list:
                m = finished_list[m_id]
                h_score = m['score']['fullTime']['home']
                a_score = m['score']['fullTime']['away']
                total = h_score + a_score

                bets = query_db("SELECT * FROM bets WHERE match_id = ? AND status = 'PENDING'", (m_id,))
                for b in bets:
                    win = False
                    if b['side'] == 'chu' and (h_score + b['handicap']) > a_score: win = True
                    elif b['side'] == 'khach' and (a_score + b['handicap']) > h_score: win = True
                    elif b['side'] == 'tai' and total > b['handicap']: win = True
                    elif b['side'] == 'xiu' and total < b['handicap']: win = True

                    if win:
                        reward = int(b['amount'] * 1.9)
                        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, b['user_id']))
                        query_db("UPDATE bets SET status = 'WIN' WHERE id = ?", (b['id'],))
                    else:
                        query_db("UPDATE bets SET status = 'LOSS' WHERE id = ?", (b['id'],))
        print("✅ Đã trả thưởng xong các trận kết thúc.")
    except: pass

# ================= 🏟️ INTERFACE CƯỢC & MINI GAME =================

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, can_bet=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not can_bet: self.clear_items() # Nếu là kênh Live thì xóa nút cược

    async def handle_bet(self, i, side, team, line):
        start_time = parse_utc(self.m['utcDate'])
        if (start_time - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Trận đấu đã chuẩn bị đá hoặc đang đá. Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], side, team, line))

    @ui.button(label="🏠 Cược Chủ", style=discord.ButtonStyle.primary, row=0)
    async def c1(self, i, b): await self.handle_bet(i, "chu", self.m['homeTeam']['name'], self.hcap)

    @ui.button(label="✈️ Cược Khách", style=discord.ButtonStyle.danger, row=0)
    async def c2(self, i, b): await self.handle_bet(i, "khach", self.m['awayTeam']['name'], -self.hcap)

    @ui.button(label="🔥 Tài (Over)", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await self.handle_bet(i, "tai", "Tài", self.ou)

    @ui.button(label="❄️ Xỉu (Under)", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await self.handle_bet(i, "xiu", "Xỉu", self.ou)

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Tối thiểu 10,000...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (i.user.id, self.m_id, self.side, val, self.line))
            await i.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}**", ephemeral=True)
        except: await i.response.send_message("❌ Nhập số tiền hợp lệ!", ephemeral=True)

class TaiXiuView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label="TÀI", style=discord.ButtonStyle.danger)
    async def tai(self, i, b): await i.response.send_modal(TXMiniModal("Tài"))
    @ui.button(label="XỈU", style=discord.ButtonStyle.primary)
    async def xiu(self, i, b): await i.response.send_modal(TXMiniModal("Xỉu"))
    @ui.button(label="SOI CẦU MINI 🔍", style=discord.ButtonStyle.secondary)
    async def soi(self, i, b):
        c = random.choice(["Bệt Tài", "Cầu 1-1", "Nghiêng Xỉu", "Cầu 2-2"])
        await i.response.send_message(f"📊 **Soi cầu Mini:** `{c}`", ephemeral=True)

class TXMiniModal(ui.Modal, title='🎲 TÀI XỈU MINI'):
    amt = ui.TextInput(label='Số tiền cược')
    def __init__(self, choice):
        super().__init__()
        self.choice = choice
    async def on_submit(self, i: discord.Interaction):
        val = int(self.amt.value)
        dice = [random.randint(1,6) for _ in range(3)]
        res = "Tài" if sum(dice) >= 11 else "Xỉu"
        if self.choice == res:
            query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, i.user.id))
            await i.response.send_message(f"🎉 THẮNG! Kết quả: {sum(dice)} ({res}) | 🎲: {dice}")
        else:
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            await i.response.send_message(f"💀 THUA! Kết quả: {sum(dice)} ({res}) | 🎲: {dice}")

# ================= 🔄 LOOP TỰ ĐỘNG PHÂN LOẠI KÊNH =================

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        all_m = [m for m in res.get('matches', []) if m['competition']['code'] in ALLOWED_LEAGUES]
        
        # 1. Kênh Cược (Chỉ hiện trận TIMED)
        if ch_cuoc:
            await ch_cuoc.purge(limit=15, check=lambda m: m.author == bot.user)
            upcoming = [m for m in all_m if m['status'] == "TIMED"][:10]
            for m in upcoming:
                h, o = get_smart_hcap(m), get_ou_line(m['homeTeam']['id'], m['awayTeam']['id'])
                # Kiểm tra cược có khóa không (trước 5 phút)
                can_bet = (parse_utc(m['utcDate']) - datetime.now(timezone.utc)).total_seconds() > 300
                emb = discord.Embed(title=f"🏟️ {m['competition']['name']}", color=0x3498db)
                emb.description = (f"🕒 Giờ đá: **{vn_time(m['utcDate'])}**\n━━━━━━━━━━━━\n"
                                   f"⚖️ **KÈO CHẤP**\n🏠 {m['homeTeam']['name']}: `{h:+0.2g}`\n"
                                   f"✈️ {m['awayTeam']['name']}: `{-h:+0.2g}`\n━━━━━━━━━━━━\n"
                                   f"⚽ **KÈO TÀI XỈU**\n🔥 Tài: `>{o}`\n❄️ Xỉu: `<{o}`")
                await ch_cuoc.send(embed=emb, view=MatchControlView(m, h, o, can_bet=can_bet))

        # 2. Kênh Live (Chỉ hiện trận ĐANG ĐÁ)
        if ch_live:
            await ch_live.purge(limit=15, check=lambda m: m.author == bot.user)
            live = [m for m in all_m if m['status'] in ["IN_PLAY", "LIVE", "PAUSED"]]
            for m in live:
                emb = discord.Embed(title="🔴 LIVE SCORE", color=0xe74c3c)
                emb.description = f"**{m['homeTeam']['name']}** `{m['score']['fullTime']['home']}` - `{m['score']['fullTime']['away']}` **{m['awayTeam']['name']}**"
                await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, can_bet=False))
    except: pass

# ================= ⚙️ COMMANDS =================

@bot.command()
async def taixiu(ctx):
    await ctx.send(embed=discord.Embed(title="🎲 TÀI XỈU MINI GAME", color=0xf1c40f), view=TaiXiuView())

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{u['coins'] if u else 0:,}** Cash")

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    auto_settle_bets.start()
    print(f"🚀 {bot.user.name} READY!")

bot.run(TOKEN)
