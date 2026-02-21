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
ID_BONG_DA = 1474672512708247582 
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

# --- LOGIC THỜI GIAN & KÈO ---
def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def vn_now():
    return datetime.now(timezone(timedelta(hours=7)))

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

def get_smart_hcap(m):
    custom = query_db("SELECT hcap FROM custom_hcap WHERE match_id = ?", (m['id'],), one=True)
    if custom: return custom['hcap']
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{m['competition']['code']}/standings"
        res = requests.get(url, headers=headers, timeout=5).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        diff = ranks.get(m['awayTeam']['id'], 10) - ranks.get(m['homeTeam']['id'], 10)
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.0

# --- PHÂN TÍCH SOI CẦU (AI GỢI Ý) ---
def get_match_analysis(home_id, away_id):
    try:
        headers = {"X-Auth-Token": API_KEY}
        url_home = f"https://api.football-data.org/v4/teams/{home_id}/matches?status=FINISHED&limit=5"
        url_away = f"https://api.football-data.org/v4/teams/{away_id}/matches?status=FINISHED&limit=5"
        
        h_res = requests.get(url_home, headers=headers).json()
        a_res = requests.get(url_away, headers=headers).json()
        
        def calc_form(matches, t_id):
            pts = 0
            for m in matches.get('matches', []):
                win = m['score']['winner']
                if win == "DRAW": pts += 1
                elif (win == "HOME_TEAM" and m['homeTeam']['id'] == t_id) or \
                     (win == "AWAY_TEAM" and m['awayTeam']['id'] == t_id): pts += 3
            return pts

        h_pts = calc_form(h_res, home_id)
        a_pts = calc_form(a_res, away_id)
        
        if h_pts > a_pts: return f"📈 Gợi ý: **Cửa Trên** (Phong độ {h_pts}/15đ)"
        elif a_pts > h_pts: return f"📈 Gợi ý: **Cửa Dưới** (Phong độ {a_pts}/15đ)"
        else: return "⚖️ Gợi ý: **Hòa hoãn** (Phong độ ngang nhau)"
    except: return "❌ Không đủ dữ liệu để soi cầu lúc này."

# ================= 🛒 HỆ THỐNG SHOP & TICKET =================

class ShopView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def buy_item(self, interaction: discord.Interaction, item, price):
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not u or u['coins'] < price:
            return await interaction.response.send_message(f"❌ Bạn cần `{price:,}` Cash!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        ch = await guild.create_text_channel(name=f"🛒-{interaction.user.name}", overwrites=overwrites)
        embed = discord.Embed(title="📦 ĐƠN HÀNG MỚI", color=0xf1c40f)
        embed.description = f"Người mua: {interaction.user.mention}\nVật phẩm: **{item}**\nGiá: `{price:,}` Cash"
        await ch.send(content="@here", embed=embed)
        await interaction.response.send_message(f"✅ Đã thanh toán! Kiểm tra {ch.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.secondary, emoji="🏷️")
    async def i1(self, i, b): await self.buy_item(i, "Thẻ Đổi Tên", 50000)

    @ui.button(label="Role Tùy Chỉnh (500k)", style=discord.ButtonStyle.secondary, emoji="👑")
    async def i2(self, i, b): await self.buy_item(i, "Role Tùy Chỉnh", 500000)

# ================= 🎲 MINI GAME: TÀI XỈU =================

class TaiXiuModal(ui.Modal, title='🎲 TÀI XỈU VERDICT'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Nhập từ 10k đến 5M...')
    def __init__(self, choice):
        super().__init__()
        self.choice = choice

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000 or val > 5000000: return await interaction.response.send_message("❌ Mức cược: 10k - 5M!", ephemeral=True)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not u or u['coins'] < val: return await interaction.response.send_message("❌ Không đủ Cash!", ephemeral=True)

            is_win = random.random() > 0.53
            dice = [random.randint(1,6) for _ in range(3)]
            total = sum(dice)
            
            res_type = "Tài" if total >= 11 else "Xỉu"
            if is_win and res_type != self.choice: total = 11 if self.choice == "Tài" else 4
            elif not is_win and res_type == self.choice: total = 4 if self.choice == "Tài" else 11
            
            final_res = "Tài" if total >= 11 else "Xỉu"
            if is_win:
                query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, interaction.user.id))
                color, msg = 0x2ecc71, "🎉 BẠN ĐÃ THẮNG"
            else:
                query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
                color, msg = 0xe74c3c, "💀 BẠN ĐÃ THUA"

            embed = discord.Embed(title=f"{msg} ({self.choice})", color=color)
            embed.description = f"🎲 Kết quả: **{total} điểm ({final_res})**\n💰 Tiền: `{val:,}` Cash"
            await interaction.response.send_message(embed=embed)
        except: await interaction.response.send_message("❌ Lỗi dữ liệu!", ephemeral=True)

# ================= 🏟️ SCOREBOARD & PHIẾU CƯỢC =================

class MatchControlView(ui.View):
    def __init__(self, match_data, hcap):
        super().__init__(timeout=None)
        self.m = match_data
        self.hcap = hcap

    @ui.button(label="Cược Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b):
        await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['name'], self.hcap))

    @ui.button(label="Cược Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b):
        await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['name'], -self.hcap))

    @ui.button(label="Soi Cầu 🔍", style=discord.ButtonStyle.secondary)
    async def analysis(self, i, b):
        await i.response.defer(ephemeral=True)
        tip = get_match_analysis(self.m['homeTeam']['id'], self.m['awayTeam']['id'])
        await i.followup.send(embed=discord.Embed(title="🔍 SOI CẦU", description=tip, color=0xf1c40f), ephemeral=True)

    @ui.button(label="Làm mới 🔄", style=discord.ButtonStyle.success)
    async def refresh(self, i, b):
        await i.response.send_message("🔄 Đang cập nhật...", ephemeral=True)
        await update_scoreboard()

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='10k - 5M...')
    def __init__(self, m_id, side, team, hcap):
        super().__init__()
        self.m_id = m_id
        self.side = side
        self.team = team
        self.hcap = hcap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            user_id = interaction.user.id

            # 1. Kiểm tra mức tiền
            if val < 10000 or val > 5000000: 
                return await interaction.response.send_message("❌ Mức cược: 10,000 - 5,000,000 Cash!", ephemeral=True)

            # 2. KIỂM TRA CHỈ ĐƯỢC CƯỢC 1 ĐỘI DUY NHẤT
            existing = query_db("SELECT id FROM bets WHERE user_id = ? AND match_id = ? AND status = 'PENDING'", (user_id, self.m_id), one=True)
            if existing:
                return await interaction.response.send_message("⚠️ Bạn đã đặt cược cho trận này rồi! Mỗi trận chỉ được chọn 1 đội duy nhất.", ephemeral=True)

            # 3. Kiểm tra ví tiền
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (user_id,), one=True)
            if not u or u['coins'] < val: 
                return await interaction.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)
            
            # 4. Trừ tiền và ghi nhận cược
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, user_id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (user_id, self.m_id, self.side, val, self.hcap))
            
            ticket = discord.Embed(title="🎫 VÉ CƯỢC XÁC NHẬN", color=0x3498db)
            ticket.add_field(name="🏟️ Trận", value=f"#{self.m_id}", inline=True)
            ticket.add_field(name="🚩 Đội", value=self.team, inline=True)
            ticket.add_field(name="⚖️ Kèo", value=f"{self.hcap:+0.2g}", inline=True)
            ticket.add_field(name="💰 Tiền", value=f"{val:,} Cash", inline=True)
            
            try: await interaction.user.send(embed=ticket)
            except: pass
            
            await interaction.response.send_message(f"✅ Đã đặt cược thành công cho **{self.team}**!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Vui lòng nhập số tiền hợp lệ!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Lỗi hệ thống: {e}", ephemeral=True)

# ================= ✨ BẢNG XẾP HẠNG =================

@tasks.loop(minutes=30)
async def update_bxh():
    ch = bot.get_channel(ID_BXH)
    if not ch: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG TRIỆU PHÚ ✨", color=0xffd700)
    medals = ["🥇", "🥈", "🥉", "👤", "👤", "👤", "👤", "👤", "👤", "👤"]
    lb = ""
    for i, r in enumerate(top):
        lb += f"{medals[i]} `#{i+1:02}` <@{r['user_id']}> — **{r['coins']:,}** 💸\n"
    embed.description = f"💎 **Đại gia Server**\n━━━━━━━━━━━━━━━━━━━━\n{lb or 'Chưa có dữ liệu'}"
    embed.set_footer(text=f"Cập nhật: {vn_now().strftime('%H:%M:%S')}")
    await ch.purge(limit=5, check=lambda m: m.author == bot.user)
    await ch.send(embed=embed)

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch = bot.get_channel(ID_BONG_DA)
    if not ch: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        active = [m for m in res.get('matches', []) if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "TIMED", "PAUSED", "LIVE"]][:5]
        await ch.purge(limit=15, check=lambda m: m.author == bot.user)
        for m in active:
            hcap = get_smart_hcap(m)
            is_live = m['status'] == "IN_PLAY"
            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0xff4757 if is_live else 0x2f3542)
            embed.description = (
                f"{'🔴 **LIVE**' if is_live else '🕒 ' + vn_time(m['utcDate'])}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏠 **{m['homeTeam']['name']}**: `{m['score']['fullTime']['home'] or 0}`\n"
                f"✈️ **{m['awayTeam']['name']}**: `{m['score']['fullTime']['away'] or 0}`\n\n"
                f"⚖️ **KÈO CHẤP**: {m['homeTeam']['shortName']} `{hcap:+0.2g}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            embed.set_footer(text=f"🆔 ID: {m['id']} • Verdict Master")
            await ch.send(embed=embed, view=MatchControlView(m, hcap))
    except: pass

# ================= ⚙️ CORE COMMANDS =================

@bot.event
async def on_interaction(interaction):
    if interaction.type == discord.InteractionType.component:
        cid = interaction.data.get('custom_id')
        if cid == "tx_tai": await interaction.response.send_modal(TaiXiuModal("Tài"))
        elif cid == "tx_xiu": await interaction.response.send_modal(TaiXiuModal("Xỉu"))

@bot.command()
async def shop(ctx):
    await ctx.send(embed=discord.Embed(title="🛒 SHOP VERDICT", color=0x3498db), view=ShopView())

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(embed=discord.Embed(title="💳 VÍ", description=f"💰: **{u['coins'] if u else 0:,}** Cash", color=0x2ecc71))

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` cho {user.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    query_db('CREATE TABLE IF NOT EXISTS custom_hcap (match_id INTEGER PRIMARY KEY, hcap REAL)')
    update_scoreboard.start()
    update_bxh.start()
    print(f"🚀 {bot.user.name} READY!")

bot.run(TOKEN)
