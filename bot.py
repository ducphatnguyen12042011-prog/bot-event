import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- 1. KHỞI TẠO CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ODDS_KEY = os.getenv('ODDS_API_KEY') 
ID_KENH_CUOC = 1474793205299155135
ID_KENH_LIVE = 1474672512708247582
ALLOWED_LEAGUES = ['PL', 'PD', 'CL', 'BL1', 'SA']

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

def fetch_odds_from_api(home_team_name):
    """Lấy kèo từ Odds API (Cập nhật chuẩn xác)"""
    if not ODDS_KEY: return 0.5, 2.5
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds"
    params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'spreads,totals', 'oddsFormat': 'decimal'}
    try:
        res = requests.get(url, params=params).json()
        for data in res:
            if home_team_name in data['home_team'] or data['home_team'] in home_team_name:
                h, o = 0.5, 2.5
                for bookie in data['bookmakers']:
                    if bookie['key'] in ['pinnacle', 'onexbet', 'be88', 'betfair_ex_eu']:
                        for market in bookie['markets']:
                            if market['key'] == 'spreads': h = market['outcomes'][0]['point']
                            if market['key'] == 'totals': o = market['outcomes'][0]['point']
                        return h, o
        return 0.5, 2.5
    except: return 0.5, 2.5

# --- 4. TỰ ĐỘNG TRẢ THƯỞNG (ĐÃ CẬP NHẬT LOGIC HÒA) ---
@tasks.loop(minutes=5)
async def auto_payout():
    headers = {"X-Auth-Token": API_KEY}
    try:
        response = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers=headers)
        data = response.json()
        for match in data.get('matches', []):
            m_id = match['id']
            bets = query_db("SELECT * FROM bets WHERE match_id = ? AND status = 'PENDING'", (m_id,))
            if not bets: continue

            h_score = match['score']['fullTime']['home']
            a_score = match['score']['fullTime']['away']
            total = h_score + a_score

            for b in bets:
                won = False
                draw_refund = False # Hoàn tiền nếu hòa kèo

                # 1. Kèo Hòa 1x2 (Thắng nếu tỉ số bằng nhau)
                if b['side'] == 'hoa':
                    if h_score == a_score: won = True

                # 2. Kèo Chấp (Handicap)
                elif b['side'] == 'chu':
                    diff = (h_score - a_score) + b['handicap']
                    if diff > 0: won = True
                    elif diff == 0: draw_refund = True
                elif b['side'] == 'khach':
                    # handicap được lưu dựa theo đội khách
                    diff = (a_score - h_score) + b['handicap']
                    if diff > 0: won = True
                    elif diff == 0: draw_refund = True

                # 3. Kèo Tài/Xỉu
                elif b['side'] == 'tai':
                    if total > b['handicap']: won = True
                    elif total == b['handicap']: draw_refund = True
                elif b['side'] == 'xiu':
                    if total < b['handicap']: won = True
                    elif total == b['handicap']: draw_refund = True

                # Thực hiện cập nhật tiền
                if won:
                    rate = 3.0 if b['side'] == 'hoa' else 1.95
                    payout = int(b['amount'] * rate)
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (payout, b['user_id']))
                    query_db("UPDATE bets SET status = 'WON' WHERE id = ?", (b['id'],))
                elif draw_refund:
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (b['amount'], b['user_id']))
                    query_db("UPDATE bets SET status = 'DRAW' WHERE id = ?", (b['id'],))
                else:
                    query_db("UPDATE bets SET status = 'LOST' WHERE id = ?", (b['id'],))
    except Exception as e:
        print(f"Lỗi auto_payout: {e}")

# --- 5. MODAL ĐẶT CƯỢC (ĐÃ CẬP NHẬT HIỂN THỊ) ---
class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(
        label='Số tiền cược', 
        placeholder='Tối thiểu 10,000...',
        min_length=5,
        max_length=15
    )
    
    def __init__(self, m_id, side, team, line, type_bet):
        super().__init__()
        self.m_id, self.side, self.team, self.line, self.type_bet = m_id, side, team, line, type_bet

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000: 
                return await i.response.send_message("❌ Cược tối thiểu 10,000!", ephemeral=True)
            
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val:
                return await i.response.send_message("❌ Bạn không đủ tiền trong tài khoản!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", 
                     (i.user.id, self.m_id, self.side, val, self.line))

            await i.response.send_message(f"✅ Đã nhận lệnh cược `{val:,}` cho **{self.team}**", ephemeral=True)

            try:
                # CẬP NHẬT HIỂN THỊ BIÊN LAI
                if self.type_bet == 'hcap':
                    line_display = f"Chấp {self.line:+0.2g}"
                    bet_type_name = "🎯 CƯỢC CHẤP"
                elif self.type_bet == '1x2':
                    line_display = "Tỉ số Hòa"
                    bet_type_name = "🤝 KÈO 1X2"
                else:
                    line_display = f"{'TÀI' if self.side == 'tai' else 'XỈU'} {self.line}"
                    bet_type_name = "📈 TÀI XỈU"

                receipt = discord.Embed(
                    title="🎫 VÉ CƯỢC ĐÃ XÁC NHẬN",
                    description=f"Mã trận: `#{self.m_id}`\n━━━━━━━━━━━━━━━━━━",
                    color=0x2ecc71
                )
                receipt.add_field(name="🚩 Lựa chọn", value=f"**{self.team}**", inline=True)
                receipt.add_field(name="⚖️ Tỷ lệ", value=f"`{line_display}`", inline=True)
                receipt.add_field(name="💰 Tiền cược", value=f"**{val:,}** Cash", inline=False)
                receipt.add_field(name="📝 Loại kèo", value=bet_type_name, inline=True)
                receipt.add_field(name="🕒 Thời gian", value=datetime.now().strftime('%H:%M:%S %d/%m'), inline=True)
                receipt.set_footer(text="Hệ thống đã ghi nhận • Chúc bạn may mắn!")
                
                await i.user.send(embed=receipt)
            except: pass
        except ValueError:
            await i.response.send_message("❌ Vui lòng chỉ nhập số nguyên!", ephemeral=True)

# --- 6. GIAO DIỆN NÚT BẤM (ĐÃ THÊM NÚT HÒA) ---
class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou

    @ui.button(label="🏠 Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b): 
        await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['name'], self.hcap, 'hcap'))

    @ui.button(label="🤝 Hòa", style=discord.ButtonStyle.secondary)
    async def c_draw(self, i, b): 
        await i.response.send_modal(BetModal(self.m['id'], "hoa", "Hòa (1x2)", 0, '1x2'))

    @ui.button(label="✈️ Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b): 
        await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['name'], -self.hcap, 'hcap'))

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): 
        await i.response.send_modal(BetModal(self.m['id'], "tai", "Tài", self.ou, 'ou'))

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): 
        await i.response.send_modal(BetModal(self.m['id'], "xiu", "Xỉu", self.ou, 'ou'))

# --- 7. SHOP & TÀI XỈU MINI ---
class ShopView(ui.View):
    def __init__(self): 
        super().__init__(timeout=None)
        
    @ui.select(placeholder="Chọn đồ muốn mua...", options=[
        discord.SelectOption(label="Danh hiệu: Đại Gia", value="daigia", description="5,000,000 Cash", emoji="💎"),
        discord.SelectOption(label="Danh hiệu: Thần Bài", value="thanbai", description="2,000,000 Cash", emoji="🃏")
    ])
    async def callback(self, i, select):
        prices = {"daigia": 5000000, "thanbai": 2000000}
        cost = prices.get(select.values[0])
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        if not u or u['coins'] < cost: 
            return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, i.user.id))
        await i.response.send_message("✅ Giao dịch thành công!", ephemeral=True)

class TaiXiuView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.history = [random.choice(["Tài", "Xỉu"]) for _ in range(10)]
        
    @ui.button(label="🔴 TÀI", style=discord.ButtonStyle.danger)
    async def tai(self, i, b): 
        await i.response.send_modal(TaiXiuMiniModal("Tài", self))
        
    @ui.button(label="🔵 XỈU", style=discord.ButtonStyle.primary)
    async def xiu(self, i, b): 
        await i.response.send_modal(TaiXiuMiniModal("Xỉu", self))
        
    @ui.button(label="🔍 SOI CẦU", style=discord.ButtonStyle.secondary)
    async def soi(self, i, b):
        cau = " -> ".join([f"`{x}`" for x in self.history])
        await i.response.send_message(embed=discord.Embed(title="📊 Cầu gần đây", description=cau, color=0x9b59b6), ephemeral=True)

class TaiXiuMiniModal(ui.Modal, title='🎲 TÀI XỈU MINI'):
    amt = ui.TextInput(label='Tiền cược', placeholder='Nhập tiền...')
    def __init__(self, choice, parent):
        super().__init__()
        self.choice, self.parent = choice, parent
        
    async def on_submit(self, i):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: 
                return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)
            
            is_win = random.randint(1, 100) <= 48
            res = self.choice if is_win else ("Xỉu" if self.choice == "Tài" else "Tài")
            self.parent.history.append(res)
            
            if is_win:
                query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, i.user.id))
                await i.response.send_message(f"🎉 **THẮNG!** +{val:,} Cash. Kết quả: **{res}**")
            else:
                query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
                await i.response.send_message(f"💀 **THUA!** -{val:,} Cash. Kết quả: **{res}**")
        except: pass

# --- 8. TASKS: SCOREBOARD ---
@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc, ch_live = bot.get_channel(ID_KENH_CUOC), bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc: return
    now_utc = datetime.now(timezone.utc)

    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        await ch_cuoc.purge(limit=15, check=lambda m: m.author == bot.user)
        for m in [x for x in matches if x['status'] == 'TIMED' and x['competition']['code'] in ALLOWED_LEAGUES][:8]:
            m_id = m['id']
            match_time = parse_utc(m['utcDate'])
            is_locked = now_utc >= (match_time - timedelta(minutes=5))

            saved = query_db("SELECT hcap, ou FROM match_odds WHERE match_id = ?", (m_id,), one=True)
            if saved:
                hcap, ou = saved['hcap'], saved['ou']
            else:
                hcap, ou = fetch_odds_from_api(m['homeTeam']['name'])
                query_db("INSERT INTO match_odds (match_id, hcap, ou) VALUES (?, ?, ?)", (m_id, hcap, ou))

            color = 0x95a5a6 if is_locked else 0x3498db
            status_ico = "🔒" if is_locked else "✅"
            
            emb = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=color)
            emb.description = (
                f"🕒 Giờ đá: **{vn_time(m['utcDate'])}**\n"
                f"━━━━━━━━━━━━\n"
                f"⚖️ **Kèo Chấp:**\n"
                f"🏠 {m['homeTeam']['name']}: `{hcap:+0.2g}`\n"
                f"✈️ {m['awayTeam']['name']}: `{-hcap:+0.2g}`\n\n"
                f"⚽ **Kèo Tài/Xỉu:**\n"
                f"🔥 TÀI: `>{ou}` | ❄️ XỈU: `<{ou}`\n\n"
                f"{status_ico} **Trạng thái:** {'ĐÃ ĐÓNG' if is_locked else 'ĐANG MỞ'}"
            )
            
            if is_locked:
                await ch_cuoc.send(embed=emb) 
            else:
                await ch_cuoc.send(embed=emb, view=MatchControlView(m, hcap, ou))

        if ch_live:
            await ch_live.purge(limit=10, check=lambda m: m.author == bot.user)
            for m in [x for x in matches if x['status'] in ['IN_PLAY', 'LIVE', 'PAUSED']]:
                sc = m['homeTeam']['name']
                sc_a = m['awayTeam']['name']
                ft = m['score']['fullTime']
                emb_live = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
                emb_live.description = f"🏠 **{sc}** `{ft['home']}` - `{ft['away']}` **{sc_a}**"
                await ch_live.send(embed=emb_live)

    except Exception as e: 
        print(f"Lỗi scoreboard: {e}")

# --- 9. COMMANDS ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setkeo(ctx, match_id: int, hcap: float, ou: float):
    query_db("INSERT OR REPLACE INTO match_odds (match_id, hcap, ou) VALUES (?, ?, ?)", (match_id, hcap, ou))
    await ctx.send(f"✅ Đã chỉnh lại kèo cho trận #{match_id}")

@bot.command()
async def lichsu(ctx):
    bets = query_db("SELECT * FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (ctx.author.id,))
    if not bets: 
        return await ctx.send("📝 Bạn chưa có lịch sử cược.")
    
    txt = ""
    for b in bets:
        status_map = {"PENDING": "⏳ Chờ", "WON": "🎉 Thắng", "LOST": "💀 Thua", "DRAW": "🤝 Hòa"}
        txt += f"🔹 Trận `#{b['match_id']}` | {b['side'].upper()} | `{b['amount']:,}` | **{status_map.get(b['status'], b['status'])}**\n"
    
    await ctx.send(embed=discord.Embed(title="📜 LỊCH SỬ CƯỢC", description=txt, color=0x9b59b6))

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if not ctx.author.guild_permissions.administrator: return
    query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
    await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

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

# --- 10. KHỞI CHẠY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS match_odds (match_id INTEGER PRIMARY KEY, hcap REAL, ou REAL)')
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    auto_payout.start()
    print(f"🚀 {bot.user.name} Ready!")

bot.run(TOKEN)
