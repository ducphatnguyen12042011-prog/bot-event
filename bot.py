import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- 1. KHỞI TẠO CẤU HÌNH & BOT (Khai báo bot trước để tránh lỗi NameError) ---
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

# --- 4. MODAL ĐẶT CƯỢC & VÉ DM ---
class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Tối thiểu 10,000...')
    
    def __init__(self, m_id, side, team, line, type_bet):
        super().__init__()
        self.m_id, self.side, self.team, self.line, self.type_bet = m_id, side, team, line, type_bet

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000: return await i.response.send_message("❌ Cược tối thiểu 10,000!", ephemeral=True)
            
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val:
                return await i.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", 
                     (i.user.id, self.m_id, self.side, val, self.line))

            await i.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}**", ephemeral=True)

            # --- GỬI VÉ CƯỢC XÁC NHẬN VÀO DM (Mix Format Kèo) ---
            try:
                line_str = f"{self.line:+0.2g}" if self.type_bet == 'hcap' else (f">{self.line}" if self.side == 'tai' else f"<{self.line}")
                emb = discord.Embed(title="🏷️ VÉ CƯỢC XÁC NHẬN", color=0x3498db)
                emb.add_field(name="🏟️ Trận", value=f"#{self.m_id}", inline=True)
                emb.add_field(name="🚩 Chọn", value=f"{self.team}", inline=True)
                emb.add_field(name="⚖️ Kèo", value=f"`{line_str}`", inline=True)
                emb.add_field(name="💰 Tiền", value=f"{val:,} Cash", inline=False)
                emb.set_footer(text=f"Hôm nay lúc {datetime.now().strftime('%H:%M %p')}")
                await i.user.send(embed=emb)
            except:
                await i.followup.send("⚠️ Hãy mở DM để nhận vé cược xác nhận!", ephemeral=True)
        except ValueError:
            await i.response.send_message("❌ Nhập số tiền hợp lệ!", ephemeral=True)

# --- 5. GIAO DIỆN NÚT BẤM ---
class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, is_betting=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not is_betting: self.clear_items()

    @ui.button(label="🏠 Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['name'], self.hcap, 'hcap'))

    @ui.button(label="✈️ Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['name'], -self.hcap, 'hcap'))

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "tai", "Tài", self.ou, 'ou'))

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "xiu", "Xỉu", self.ou, 'ou'))

# --- 6. SHOP & TÀI XỈU MINI ---
class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.select(placeholder="Chọn đồ muốn mua...", options=[
        discord.SelectOption(label="Danh hiệu: Đại Gia", value="daigia", description="5,000,000 Cash", emoji="💎"),
        discord.SelectOption(label="Danh hiệu: Thần Bài", value="thanbai", description="2,000,000 Cash", emoji="🃏")
    ])
    async def callback(self, i, select):
        prices = {"daigia": 5000000, "thanbai": 2000000}
        item = select.options[0].label if select.values[0] == "daigia" else select.options[1].label
        cost = prices.get(select.values[0])
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        if not u or u['coins'] < cost: return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, i.user.id))
        await i.response.send_message("✅ Giao dịch thành công! Check DM nhận hóa đơn.", ephemeral=True)
        try:
            emb = discord.Embed(title="🧾 HÓA ĐƠN THANH TOÁN", color=0x2ecc71, timestamp=datetime.now())
            emb.add_field(name="Vật phẩm", value=item)
            emb.add_field(name="Giá", value=f"{cost:,} Cash")
            await i.user.send(embed=emb)
        except: pass

class TaiXiuView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.history = [random.choice(["Tài", "Xỉu"]) for _ in range(10)]
    @ui.button(label="🔴 TÀI", style=discord.ButtonStyle.danger)
    async def tai(self, i, b): await i.response.send_modal(TaiXiuMiniModal("Tài", self))
    @ui.button(label="🔵 XỈU", style=discord.ButtonStyle.primary)
    async def xiu(self, i, b): await i.response.send_modal(TaiXiuMiniModal("Xỉu", self))
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
            if not u or u['coins'] < val: return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)
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

# --- 7. TASKS: CẬP NHẬT Scoreboard (Mix đúng Format Kèo) ---
@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc, ch_live = bot.get_channel(ID_KENH_CUOC), bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc or not ch_live: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        # 1. Kênh Cược (Format Kèo Thắng/Thua, Tài/Xỉu)
        await ch_cuoc.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in [x for x in matches if x['status'] == 'TIMED' and x['competition']['code'] in ALLOWED_LEAGUES][:5]:
            hcap, ou = 0.5, 2.5
            emb = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x3498db)
            emb.description = (
                f"🕒 Giờ đá: **{vn_time(m['utcDate'])}**\n"
                f"━━━━━━━━━━━━\n"
                f"⚖️ **Kèo Thắng/Thua:**\n"
                f"🏠 {m['homeTeam']['name']}: `{hcap:+0.2g}`\n"
                f"✈️ {m['awayTeam']['name']}: `{-hcap:+0.2g}`\n\n"
                f"⚽ **Kèo Tài/Xỉu:**\n"
                f"🔥 TÀI: `>{ou}` | ❄️ XỈU: `<{ou}`"
            )
            await ch_cuoc.send(embed=emb, view=MatchControlView(m, hcap, ou, True))

        # 2. Kênh Live (Tỉ số và Tên đội)
        await ch_live.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in [x for x in matches if x['status'] in ['IN_PLAY', 'LIVE', 'PAUSED']]:
            sc = m['score']['fullTime']
            emb = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
            emb.description = f"🏠 **{m['homeTeam']['name']}** `{sc['home']}` - `{sc['away']}` **{m['awayTeam']['name']}**"
            await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, False))
    except: pass

# --- 8. COMMANDS (!nap, !vi, !shop, !taixiu) ---
@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if not ctx.author.guild_permissions.administrator: return
    query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
    await ctx.send(embed=discord.Embed(description=f"✅ Nạp `{amt:,}` Cash cho {user.mention}", color=0x2ecc71))

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

# --- 9. ON READY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    print(f"🚀 {bot.user.name} đã sẵn sàng!")

bot.run(TOKEN)
