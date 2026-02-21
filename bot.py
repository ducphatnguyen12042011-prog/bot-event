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
ID_KENH_CUOC = 1474793205299155135
ID_KENH_LIVE = 1474672512708247582
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

# ================= 💰 HỆ THỐNG TỰ ĐỘNG TRẢ THƯỞNG =================

@tasks.loop(minutes=10)
async def auto_settle_bets():
    """Quét các trận FINISHED và trả thưởng cho người dùng"""
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
                    # Logic kèo chấp
                    if b['side'] == 'chu' and (h_score + b['handicap']) > a_score: win = True
                    elif b['side'] == 'khach' and (a_score + b['handicap']) > h_score: win = True
                    # Logic Tài Xỉu
                    elif b['side'] == 'tai' and total > b['handicap']: win = True
                    elif b['side'] == 'xiu' and total < b['handicap']: win = True

                    if win:
                        reward = int(b['amount'] * 1.9)
                        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, b['user_id']))
                        query_db("UPDATE bets SET status = 'WIN' WHERE id = ?", (b['id'],))
                    else:
                        query_db("UPDATE bets SET status = 'LOSS' WHERE id = ?", (b['id'],))
        print(f"[{datetime.now()}] Đã thanh toán các vé cược hoàn tất.")
    except Exception as e:
        print(f"Lỗi Settle: {e}")

# ================= 🏟️ INTERFACE CƯỢC & MINI GAME =================

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, is_betting_channel=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not is_betting_channel: self.clear_items()

    @ui.button(label="🏠 Cược Chủ", style=discord.ButtonStyle.primary, row=0)
    async def c1(self, i, b):
        if (parse_utc(self.m['utcDate']) - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['name'], self.hcap))

    @ui.button(label="✈️ Cược Khách", style=discord.ButtonStyle.danger, row=0)
    async def c2(self, i, b):
        if (parse_utc(self.m['utcDate']) - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['name'], -self.hcap))

    @ui.button(label="🔥 Tài (Over)", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b):
        if (parse_utc(self.m['utcDate']) - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], "tai", "Tài", self.ou))

    @ui.button(label="❄️ Xỉu (Under)", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b):
        if (parse_utc(self.m['utcDate']) - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], "xiu", "Xỉu", self.ou))

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Tối thiểu 10k...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
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
        c = random.choice(["Cầu Bệt Tài", "Cầu 1-1", "Cầu Nghiêng Xỉu", "Cầu 2-2"])
        await i.response.send_message(f"📊 Dự đoán: `{c}`", ephemeral=True)

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
            await i.response.send_message(f"🎉 THẮNG! {sum(dice)} ({res}) | 🎲: {dice}")
        else:
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            await i.response.send_message(f"💀 THUA! {sum(dice)} ({res}) | 🎲: {dice}")

# ================= 🔄 LOOP & CORE =================

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        # Cập nhật Kênh Cược
        upcoming = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] == "TIMED"][:8]
        await ch_cuoc.purge(limit=15, check=lambda m: m.author == bot.user)
        for m in upcoming:
            h, o = get_smart_hcap(m), get_ou_line(m['homeTeam']['id'], m['awayTeam']['id'])
            emb = discord.Embed(title=f"🏟️ {m['competition']['name']}", color=0x3498db)
            emb.description = (f"🕒 **{vn_time(m['utcDate'])}**\n━━━━━━━━━━━━\n"
                               f"⚖️ **KÈO CHẤP**\n🏠 {m['homeTeam']['name']}: `{h:+0.2g}`\n"
                               f"✈️ {m['awayTeam']['name']}: `{-h:+0.2g}`\n━━━━━━━━━━━━\n"
                               f"⚽ **KÈO TÀI XỈU**\n🔥 Tài: `>{o}`\n❄️ Xỉu: `<{o}`")
            await ch_cuoc.send(embed=emb, view=MatchControlView(m, h, o, True))

        # Cập nhật Kênh Live
        if ch_live:
            live = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "LIVE"]]
            await ch_live.purge(limit=15, check=lambda m: m.author == bot.user)
            for m in live:
                emb = discord.Embed(title="🔴 LIVE", color=0xe74c3c)
                emb.description = f"**{m['homeTeam']['name']}** `{m['score']['fullTime']['home']}` - `{m['score']['fullTime']['away']}` **{m['awayTeam']['name']}**"
                await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, False))
    except: pass

@bot.command()
async def taixiu(ctx):
    await ctx.send(embed=discord.Embed(title="🎲 TÀI XỈU MINI"), view=TaiXiuView())

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 Ví: **{u['coins'] if u else 0:,}** Cash")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    auto_settle_bets.start()
    print(f"🚀 {bot.user.name} Online!")

bot.run(TOKEN)
