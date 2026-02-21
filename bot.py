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
ID_KENH_CUOC = 1474793205299155135  # Kênh nghiên cứu & đặt cược
ID_KENH_LIVE = 1474672512708247582  # Kênh theo dõi trận đấu
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

# --- LOGIC THỜI GIAN & HỖ TRỢ ---
def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

def get_smart_hcap(m):
    # Kèo chấp Handicap
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{m['competition']['code']}/standings"
        res = requests.get(url, headers=headers, timeout=5).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        diff = ranks.get(m['awayTeam']['id'], 10) - ranks.get(m['homeTeam']['id'], 10)
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.5

def get_over_under_line(home_id, away_id):
    # Kèo Tài Xỉu (Tính trung bình bàn thắng)
    try:
        headers = {"X-Auth-Token": API_KEY}
        h_res = requests.get(f"https://api.football-data.org/v4/teams/{home_id}/matches?status=FINISHED&limit=5", headers=headers).json()
        a_res = requests.get(f"https://api.football-data.org/v4/teams/{away_id}/matches?status=FINISHED&limit=5", headers=headers).json()
        total_goals = 0
        matches = h_res.get('matches', []) + a_res.get('matches', [])
        if not matches: return 2.5
        for m in matches:
            total_goals += (m['score']['fullTime']['home'] + m['score']['fullTime']['away'])
        avg = total_goals / len(matches)
        return round(avg * 2) / 2 if avg > 0 else 2.5
    except: return 2.5

def get_full_analysis(m):
    # Soi cầu tổng hợp
    try:
        headers = {"X-Auth-Token": API_KEY}
        h_id, a_id = m['homeTeam']['id'], m['awayTeam']['id']
        h_res = requests.get(f"https://api.football-data.org/v4/teams/{h_id}/matches?status=FINISHED&limit=5", headers=headers).json()
        a_res = requests.get(f"https://api.football-data.org/v4/teams/{a_id}/matches?status=FINISHED&limit=5", headers=headers).json()
        
        # Phân tích kèo chấp
        def get_pts(res, t_id):
            p = 0
            for mt in res.get('matches', []):
                w = mt['score']['winner']
                if w == "DRAW": p += 1
                elif (w == "HOME_TEAM" and mt['homeTeam']['id'] == t_id) or (w == "AWAY_TEAM" and mt['awayTeam']['id'] == t_id): p += 3
            return p
        
        h_pts, a_pts = get_pts(h_res, h_id), get_pts(a_res, a_id)
        side_tip = "Cửa Trên" if h_pts >= a_pts else "Cửa Dưới"
        
        # Phân tích Tài Xỉu
        all_m = h_res.get('matches', []) + a_res.get('matches', [])
        avg = sum((x['score']['fullTime']['home'] + x['score']['fullTime']['away']) for x in all_m) / len(all_m)
        ou_tip = "Tài (Over)" if avg > 2.7 else "Xỉu (Under)"
        
        return f"📊 **PHÂN TÍCH AI**:\n• Kèo chấp: Nên chọn **{side_tip}**\n• Tài Xỉu: Nên chọn **{ou_tip}**\n• Hiệu suất ghi bàn: `{avg:.2f}` bàn/trận."
    except: return "❌ Dữ liệu không đủ."

# ================= 🏟️ HỆ THỐNG GIAO DIỆN =================

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, can_bet=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not can_bet: self.clear_items()

    def is_locked(self):
        start_time = parse_utc(self.m['utcDate'])
        return (start_time - datetime.now(timezone.utc)).total_seconds() < 300 # 5 phút

    async def handle_bet(self, i, side, team, line):
        if self.is_locked():
            return await i.response.send_message("❌ Trận đấu đã khóa cược (5 phút trước giờ đá hoặc đang đá)!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], side, team, line))

    @ui.button(label="Cược Chủ", style=discord.ButtonStyle.primary, row=0)
    async def c1(self, i, b): await self.handle_bet(i, "chu", self.m['homeTeam']['name'], self.hcap)

    @ui.button(label="Cược Khách", style=discord.ButtonStyle.danger, row=0)
    async def c2(self, i, b): await self.handle_bet(i, "khach", self.m['awayTeam']['name'], -self.hcap)

    @ui.button(label="Tài (Over)", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await self.handle_bet(i, "tai", "Tài (Over)", self.ou)

    @ui.button(label="Xỉu (Under)", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await self.handle_bet(i, "xiu", "Xỉu (Under)", self.ou)

    @ui.button(label="Soi Cầu 🔍", style=discord.ButtonStyle.primary, row=2)
    async def analysis(self, i, b):
        await i.response.defer(ephemeral=True)
        await i.followup.send(embed=discord.Embed(description=get_full_analysis(self.m), color=0xf1c40f), ephemeral=True)

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='10k - 5M...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000 or val > 5000000: return await i.response.send_message("❌ Cược từ 10k - 5M!", ephemeral=True)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", 
                     (i.user.id, self.m_id, self.side, val, self.line))
            await i.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}** (Kèo: {self.line})", ephemeral=True)
        except: await i.response.send_message("❌ Lỗi!", ephemeral=True)

# ================= 🔄 CẬP NHẬT TỰ ĐỘNG =================

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc or not ch_live: return
    
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        # Kênh Cược
        bet_matches = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] == "TIMED"][:8]
        await ch_cuoc.purge(limit=20, check=lambda m: m.author == bot.user)
        for m in bet_matches:
            hcap = get_smart_hcap(m)
            ou = get_over_under_line(m['homeTeam']['id'], m['awayTeam']['id'])
            embed = discord.Embed(title=f"🏟️ {m['competition']['name']}", color=0x3498db)
            embed.description = f"🕒 **{vn_time(m['utcDate'])}**\n🏠 {m['homeTeam']['name']} vs ✈️ {m['awayTeam']['name']}\n\n⚖️ Chấp: `{hcap:+0.2g}`\n⚽ Tài Xỉu: `{ou}`"
            await ch_cuoc.send(embed=embed, view=MatchControlView(m, hcap, ou, True))

        # Kênh Live
        live_matches = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "PAUSED", "LIVE"]]
        await ch_live.purge(limit=20, check=lambda m: m.author == bot.user)
        if not live_matches:
            await ch_live.send(embed=discord.Embed(description="📭 Hiện không có trận live.", color=0x7f8c8d))
        for m in live_matches:
            embed = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
            embed.description = f"🏠 **{m['homeTeam']['name']}** `{m['score']['fullTime']['home']}` - `{m['score']['fullTime']['away']}` **{m['awayTeam']['name']}**"
            await ch_live.send(embed=embed, view=MatchControlView(m, 0, 0, False))
    except Exception as e: print(f"Lỗi: {e}")

# ================= ⚙️ KHỞI CHẠY =================

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    print(f"🚀 {bot.user.name} Ready!")

bot.run(TOKEN)
