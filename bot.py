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

# ID các kênh phân biệt
ID_KENH_CUOC = 1474793205299155135  # Chỉ hiện trận CHƯA ĐÁ
ID_KENH_LIVE = 1474672512708247582  # Chỉ hiện trận ĐANG ĐÁ
ALLOWED_LEAGUES = ['PL', 'PD', 'CL']

intents = discord.Intents.all()
# Khởi tạo bot ngay từ đầu để tránh lỗi "bot is not defined"
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

# --- 3. HELPERS ---
def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

def get_smart_hcap(m):
    return 0.5  # Logic kèo chấp mặc định

def get_ou_line(home_id, away_id):
    return 2.5  # Logic tài xỉu mặc định

# --- 4. HỆ THỐNG TỰ ĐỘNG TRẢ THƯỞNG (SETTLE) ---
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
                    # Tính toán thắng thua
                    if b['side'] == 'chu' and (h_score + b['handicap']) > a_score: win = True
                    elif b['side'] == 'khach' and (a_score + b['handicap']) > h_score: win = True
                    elif b['side'] == 'tai' and total > b['handicap']: win = True
                    elif b['side'] == 'xiu' and total < b['handicap']: win = True

                    if win:
                        reward = int(b['amount'] * 1.9) # Tỷ lệ thưởng 1.9
                        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, b['user_id']))
                        query_db("UPDATE bets SET status = 'WIN' WHERE id = ?", (b['id'],))
                    else:
                        query_db("UPDATE bets SET status = 'LOSS' WHERE id = ?", (b['id'],))
        print("✅ Đã thanh toán tiền cược cho các trận vừa kết thúc.")
    except Exception as e:
        print(f"Lỗi trả thưởng: {e}")

# --- 5. GIAO DIỆN CƯỢC & SHOP ---

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược (Cash)', placeholder='Tối thiểu 10,000...')
    def __init__(self, m_id, side, team, line):
        super().__init__()
        self.m_id, self.side, self.team, self.line = m_id, side, team, line

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: 
                return await i.response.send_message("❌ Bạn không đủ tiền trong ví!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", 
                     (i.user.id, self.m_id, self.side, val, self.line))
            await i.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}** thành công!", ephemeral=True)
        except:
            await i.response.send_message("❌ Vui lòng nhập số tiền hợp lệ!", ephemeral=True)

class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, can_bet=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not can_bet: self.clear_items()

    @ui.button(label="🏠 Cược Chủ", style=discord.ButtonStyle.primary, row=0)
    async def c1(self, i, b): await self.handle_bet_click(i, "chu", self.m['homeTeam']['name'], self.hcap)

    @ui.button(label="✈️ Cược Khách", style=discord.ButtonStyle.danger, row=0)
    async def c2(self, i, b): await self.handle_bet_click(i, "khach", self.m['awayTeam']['name'], -self.hcap)

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await self.handle_bet_click(i, "tai", "Tài", self.ou)

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await self.handle_bet_click(i, "xiu", "Xỉu", self.ou)

    async def handle_bet_click(self, i, side, team, line):
        start_time = parse_utc(self.m['utcDate'])
        if (start_time - datetime.now(timezone.utc)).total_seconds() < 300:
            return await i.response.send_message("❌ Cược đã đóng!", ephemeral=True)
        await i.response.send_modal(BetModal(self.m['id'], side, team, line))

class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.select(placeholder="Chọn vật phẩm mua...", options=[
        discord.SelectOption(label="Danh hiệu: Đại Gia", value="daigia", description="5,000,000 Cash"),
        discord.SelectOption(label="Danh hiệu: Thần Bài", value="thanbai", description="2,000,000 Cash")
    ])
    async def callback(self, i, select):
        cost = 5000000 if select.values[0] == "daigia" else 2000000
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        if not u or u['coins'] < cost: return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, i.user.id))
        await i.response.send_message(f"✅ Mua thành công! Hãy liên hệ Admin.", ephemeral=True)

# --- 6. TỰ ĐỘNG CẬP NHẬT KÊNH (CUOC & LIVE) ---
@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        all_matches = res.get('matches', [])
        filtered = [m for m in all_matches if m['competition']['code'] in ALLOWED_LEAGUES]

        # Xử lý kênh Cược
        if ch_cuoc:
            await ch_cuoc.purge(limit=15, check=lambda m: m.author == bot.user)
            upcoming = [m for m in filtered if m['status'] == "TIMED"][:10]
            for m in upcoming:
                h, o = get_smart_hcap(m), get_ou_line(m['homeTeam']['id'], m['awayTeam']['id'])
                time_left = (parse_utc(m['utcDate']) - datetime.now(timezone.utc)).total_seconds()
                can_bet = time_left > 300
                emb = discord.Embed(title=f"🏟️ {m['competition']['name']}", color=0x3498db)
                emb.description = f"🕒 Khởi tranh: **{vn_time(m['utcDate'])}**\n━━━━━━━━━━━━\n⚖️ **KÈO CHẤP**: `{h:+0.2g}`\n⚽ **TÀI XỈU**: `{o}`"
                if not can_bet: emb.set_footer(text="⚠️ Cược đã đóng")
                await ch_cuoc.send(embed=emb, view=MatchControlView(m, h, o, can_bet=can_bet))

        # Xử lý kênh Live
        if ch_live:
            await ch_live.purge(limit=15, check=lambda m: m.author == bot.user)
            live = [m for m in filtered if m['status'] in ["IN_PLAY", "LIVE", "PAUSED"]]
            if not live: await ch_live.send("⏸️ Hiện không có trận nào đang đá.")
            for m in live:
                emb = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
                emb.description = f"🏠 **{m['homeTeam']['name']}** `{m['score']['fullTime']['home']}` - `{m['score']['fullTime']['away']}` **{m['awayTeam']['name']}**"
                await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, can_bet=False))
    except Exception as e: print(f"Lỗi update: {e}")

# --- 7. COMMANDS ---

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
    await ctx.send(embed=discord.Embed(title="🛒 SHOP VERDICT", color=0x3498db), view=ShopView())

# --- 8. KHỞI CHẠY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    if not update_scoreboard.is_running(): update_scoreboard.start()
    if not auto_settle_bets.is_running(): auto_settle_bets.start()
    print(f"🚀 Bot {bot.user.name} READY!")

bot.run(TOKEN)
