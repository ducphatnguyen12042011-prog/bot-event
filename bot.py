import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- 1. KHỞI TẠO CẤU HÌNH & BOT ---
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

# --- 4. MODAL ĐẶT CƯỢC ---
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
            if not u or u['coins'] < val:
                return await i.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", 
                     (i.user.id, self.m_id, self.side, val, self.line))

            await i.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}**", ephemeral=True)

            try:
                embed_dm = discord.Embed(title="🏷️ VÉ CƯỢC XÁC NHẬN", color=0x3498db)
                embed_dm.add_field(name="🏟️ Trận", value=f"#{self.m_id}", inline=True)
                embed_dm.add_field(name="🚩 Đội", value=f"{self.team}", inline=True)
                embed_dm.add_field(name="⚖️ Kèo", value=f"{self.line:+0.2g}", inline=True)
                embed_dm.add_field(name="💰 Tiền", value=f"{val:,} Cash", inline=False)
                embed_dm.set_footer(text=f"Hôm nay lúc {datetime.now().strftime('%H:%M %p')}")
                await i.user.send(embed=embed_dm)
            except:
                await i.followup.send("⚠️ Bot không gửi được DM. Vui lòng mở DM để nhận vé cược!", ephemeral=True)
        except ValueError:
            await i.response.send_message("❌ Nhập số tiền hợp lệ!", ephemeral=True)

# --- 5. GIAO DIỆN ĐIỀU KHIỂN TRẬN ĐẤU ---
class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou, is_betting=True):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou
        if not is_betting: self.clear_items()

    @ui.button(label="🏠 Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['name'], self.hcap))

    @ui.button(label="✈️ Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['name'], -self.hcap))

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "tai", "Tài", self.ou))

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "xiu", "Xỉu", self.ou))

# --- 6. HỆ THỐNG SHOP & MINI GAME ---
class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.select(placeholder="Chọn vật phẩm mua...", options=[
        discord.SelectOption(label="Danh hiệu: Đại Gia", value="daigia", description="5,000,000 Cash", emoji="💎"),
        discord.SelectOption(label="Danh hiệu: Thần Bài", value="thanbai", description="2,000,000 Cash", emoji="🃏")
    ])
    async def callback(self, i, select):
        prices = {"daigia": 5000000, "thanbai": 2000000}
        item_name = select.options[0].label if select.values[0] == "daigia" else select.options[1].label
        cost = prices.get(select.values[0])
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
        if not u or u['coins'] < cost: return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, i.user.id))
        await i.response.send_message("✅ Thành công! Kiểm tra DM.", ephemeral=True)
        try:
            emb = discord.Embed(title="🧾 HÓA ĐƠN", color=0x2ecc71, timestamp=datetime.now())
            emb.add_field(name="Món đồ", value=item_name)
            emb.add_field(name="Giá", value=f"{cost:,}")
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
    async def soi_cau(self, i, b):
        cau_str = " -> ".join([f"`{x}`" for x in self.history])
        await i.response.send_message(embed=discord.Embed(title="📊 Lịch sử", description=cau_str, color=0x9b59b6), ephemeral=True)

class TaiXiuMiniModal(ui.Modal, title='🎲 TÀI XỈU MINI'):
    amt = ui.TextInput(label='Tiền cược', placeholder='Nhập số tiền...')
    def __init__(self, choice, parent):
        super().__init__()
        self.choice, self.parent = choice, parent
    async def on_submit(self, i):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Thiếu tiền!", ephemeral=True)
            is_win = random.randint(1, 100) <= 48
            res = self.choice if is_win else ("Xỉu" if self.choice == "Tài" else "Tài")
            self.parent.history.append(res)
            if is_win:
                query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, i.user.id))
                await i.response.send_message(f"🎉 **THẮNG!** +{val:,}. Kết quả: **{res}**")
            else:
                query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))
                await i.response.send_message(f"💀 **THUA!** -{val:,}. Kết quả: **{res}**")
        except: pass

# --- 7. TASKS: CẬP NHẬT TỈ SỐ LIVE & TRẢ THƯỞNG ---
@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc or not ch_live: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        # Cập nhật kênh Cược
        await ch_cuoc.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in [x for x in matches if x['status'] == 'TIMED' and x['competition']['code'] in ALLOWED_LEAGUES][:5]:
            emb = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x3498db)
            emb.description = f"🏠 **{m['homeTeam']['name']}** vs **{m['awayTeam']['name']}**\n🕒 Đá lúc: {vn_time(m['utcDate'])}\n⚖️ Kèo: `+0.5` | `3.0`"
            await ch_cuoc.send(embed=emb, view=MatchControlView(m, 0.5, 3.0, True))

        # Cập nhật kênh Live
        await ch_live.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in [x for x in matches if x['status'] in ['IN_PLAY', 'LIVE', 'PAUSED']]:
            sc = m['score']['fullTime']
            emb = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
            emb.description = f"🏠 **{m['homeTeam']['name']}** `{sc['home']}` - `{sc['away']}` **{m['awayTeam']['name']}**"
            await ch_live.send(embed=emb, view=MatchControlView(m, 0, 0, False))
    except: pass

# --- 8. COMMANDS ---
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

# --- 9. EVENT ON READY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    print(f"🚀 {bot.user.name} Online!")

bot.run(TOKEN)
