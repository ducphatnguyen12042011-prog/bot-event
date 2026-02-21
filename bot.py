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
ID_KENH_LIVE = 1474672512708247582  # Kênh theo dõi trận đấu (Live)
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

# --- HỖ TRỢ LOGIC ---
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

# ================= 🏟️ HỆ THỐNG CƯỢC BÓNG ĐÁ =================

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, is_betting_channel=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not is_betting_channel: self.clear_items()

    def is_locked(self):
        start_time = parse_utc(self.m['utcDate'])
        # Trả về True nếu còn dưới 5 phút (300s) là đá
        return (start_time - datetime.now(timezone.utc)).total_seconds() < 300

    async def handle_bet(self, i, side, team, line):
        if self.is_locked():
            return await i.response.send_message("❌ Trận đấu đã khóa cược (Cách giờ đá dưới 5 phút hoặc đang đá)!", ephemeral=True)
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
    amt = ui.TextInput(label='Số tiền cược', placeholder='10k - 5M...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000 or val > 5000000: return await i.response.send_message("❌ Mức cược: 10,000 - 5,000,000 Cash!", ephemeral=True)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Bạn không đủ Cash!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (i.user.id, self.m_id, self.side, val, self.line))
            await i.response.send_message(f"✅ Đã đặt cược `{val:,}` cho **{self.team}** thành công!", ephemeral=True)
        except: await i.response.send_message("❌ Vui lòng nhập số tiền hợp lệ!", ephemeral=True)

# ================= 🎲 MINI GAME TÀI XỈU & SOI CẦU MINI =================

class TaiXiuView(ui.View):
    def __init__(self): super().__init__(timeout=None)

    @ui.button(label="TÀI", style=discord.ButtonStyle.danger)
    async def tai(self, i, b): await i.response.send_modal(TaiXiuMiniModal("Tài"))

    @ui.button(label="XỈU", style=discord.ButtonStyle.primary)
    async def xiu(self, i, b): await i.response.send_modal(TaiXiuMiniModal("Xỉu"))

    @ui.button(label="SOI CẦU MINI 🔍", style=discord.ButtonStyle.secondary)
    async def soi_cau(self, i, b):
        cầu_list = ["Bệt Tài", "Bệt Xỉu", "Cầu 1-1", "Cầu 2-2", "Cầu Đảo (1-2-3)"]
        advice = random.choice(cầu_list)
        await i.response.send_message(f"📊 **Dự đoán cầu Mini:** `{advice}`\n💡 *Gợi ý mang tính chất tham khảo!*", ephemeral=True)

class TaiXiuMiniModal(ui.Modal, title='🎲 TÀI XỈU MINI GAME'):
    amt = ui.TextInput(label='Tiền cược', placeholder='10k - 5M...')
    def __init__(self, choice):
        super().__init__()
        self.choice = choice
    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)
            
            dice = [random.randint(1,6) for _ in range(3)]
            total = sum(dice)
            res = "Tài" if total >= 11 else "Xỉu"
            
            if self.choice == res:
                query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, i.user.id))
                msg, color = f"🎉 THẮNG! Kết quả: {total} ({res})", 0x2ecc71
            else:
                query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
                msg, color = f"💀 THUA! Kết quả: {total} ({res})", 0xe74c3c
            await i.response.send_message(embed=discord.Embed(title=msg, description=f"🎲 Xúc xắc: {dice[0]} + {dice[1]} + {dice[2]}", color=color))
        except: pass

# ================= 🔄 CẬP NHẬT KÊNH TỰ ĐỘNG =================

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc or not ch_live: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        # 1. Cập nhật Kênh Cược (Trận chưa đá)
        upcoming = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] == "TIMED"][:10]
        await ch_cuoc.purge(limit=20, check=lambda m: m.author == bot.user)
        for m in upcoming:
            h = get_smart_hcap(m)
            o = get_ou_line(m['homeTeam']['id'], m['awayTeam']['id'])
            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x3498db)
            embed.description = (
                f"🕒 Giờ đá: **{vn_time(m['utcDate'])}**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⚖️ **KÈO CHẤP**\n"
                f"🏠 **{m['homeTeam']['name']}**: `{h:+0.2g}`\n"
                f"✈️ **{m['awayTeam']['name']}**: `{-h:+0.2g}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⚽ **KÈO TÀI XỈU**\n"
                f"🔥 Tài: `>{o}`\n"
                f"❄️ Xỉu: `<{o}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            embed.set_footer(text=f"ID: {m['id']} • Tự động khóa 5 phút trước giờ đá")
            await ch_cuoc.send(embed=embed, view=MatchControlView(m, h, o, True))

        # 2. Cập nhật Kênh Live (Trận đang diễn ra)
        live = [m for m in matches if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "LIVE", "PAUSED"]]
        await ch_live.purge(limit=20, check=lambda m: m.author == bot.user)
        for m in live:
            embed = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
            embed.description = (
                f"🏠 **{m['homeTeam']['name']}** `{m['score']['fullTime']['home']}`\n"
                f"✈️ **{m['awayTeam']['name']}** `{m['score']['fullTime']['away']}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏱️ Trạng thái: {m['status']}"
            )
            await ch_live.send(embed=embed, view=MatchControlView(m, 0, 0, False))
    except: pass

# ================= ⚙️ LỆNH HỆ THỐNG =================

@bot.command()
async def taixiu(ctx):
    embed = discord.Embed(title="🎲 MINI GAME TÀI XỈU", description="Hãy chọn TÀI (11-18) hoặc XỈU (3-10)!", color=0xf1c40f)
    await ctx.send(embed=embed, view=TaiXiuView())

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{u['coins'] if u else 0:,}** Cash")

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.command()
async def shop(ctx):
    from __main__ import ShopView # Nếu ShopView ở file khác, không thì bỏ dòng này
    await ctx.send(embed=discord.Embed(title="🛒 SHOP VERDICT", color=0x3498db), view=ShopView())

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    print(f"🚀 {bot.user.name} ĐÃ SẴN SÀNG!")

bot.run(TOKEN)
