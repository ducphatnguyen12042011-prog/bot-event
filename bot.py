import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

# --- CONFIG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582
ID_BXH = 1474674662792232981
ALLOWED_LEAGUES = ['PL', 'PD', 'CL'] # PL: EPL, PD: LaLiga, CL: UCL

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        return (res[0] if res and one else res)
    finally:
        conn.close()

# --- LOGIC KÈO CHẤP ---
def get_handicap(h_id, a_id, league_code):
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{league_code}/standings"
        res = requests.get(url, headers=headers).json()
        ranks = {t['team']['id']: t['position'] for st in res.get('standings', []) if st['type'] == 'TOTAL' for t in st['table']}
        h_r, a_r = ranks.get(h_id, 10), ranks.get(a_id, 10)
        return round(((a_r - h_r) / 4) * 0.25 * 4) / 4
    except: return 0.0

# ================= UI & MODAL =================

class BetModal(ui.Modal, title='🎰 PHIẾU CƯỢC VERDICT'):
    amount = ui.TextInput(label='Số tiền cược', placeholder='Nhập số Cash...')
    def __init__(self, match_id, side, team, hcap):
        super().__init__()
        self.m_id, self.side, self.team, self.hcap = match_id, side, team, hcap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
            user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not user or user['coins'] < amt: return await interaction.response.send_message("❌ Không đủ Cash!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
                     (interaction.user.id, self.m_id, self.side, amt, self.hcap))
            
            # Gửi vé qua DM
            embed = discord.Embed(title="🎫 VÉ CƯỢC XÁC NHẬN", color=0x00ff00, timestamp=datetime.now())
            embed.add_field(name="Đội chọn", value=f"**{self.team}**", inline=True)
            embed.add_field(name="Kèo chấp", value=f"`{self.hcap:+}`", inline=True)
            embed.add_field(name="Tiền cược", value=f"`{amt:,}` Cash", inline=False)
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("✅ Đã đặt cược và gửi vé vào DM!", ephemeral=True)
        except: await interaction.response.send_message("❌ Lỗi dữ liệu!", ephemeral=True)

# ================= HỆ THỐNG SHOP TICKET =================

class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)

    async def handle_buy(self, interaction, item, price):
        user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user or user['coins'] < price: return await interaction.response.send_message("❌ Không đủ tiền!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        guild = interaction.guild
        cat = discord.utils.get(guild.categories, name="TICKETS")
        overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        channel = await guild.create_text_channel(name=f"🎫-{item}-{interaction.user.name}", category=cat, overwrites=overwrites)
        await channel.send(f"🛒 {interaction.user.mention} mua **{item}**. Chờ Admin xử lý!")
        await interaction.response.send_message(f"✅ Đã tạo ticket: {channel.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.success)
    async def buy1(self, i, b): await self.handle_buy(i, "The-Doi-Ten", 50000)

# ================= TÀI XỈU & SOI CẦU =================
history_cau = []

@bot.command()
async def taixiu(ctx, side: str, amt: int):
    global history_cau
    side = side.lower()
    user = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user or user['coins'] < amt: return await ctx.send("❌ Hết tiền!")

    win = random.randint(1, 100) <= 47 # 53% Thua
    d = [random.randint(1, 6) for _ in range(3)]
    total = sum(d)
    res = "tai" if total >= 11 else "xiu"
    
    if (win and res != side) or (not win and res == side):
        total = random.randint(11, 17) if side == "tai" and win else random.randint(4, 10)
        res = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt if side == res else -amt, ctx.author.id))
    history_cau.append(total)
    await ctx.send(f"🎲 Kết quả: **{total}** ({res.upper()}). Bạn **{'THẮNG' if side == res else 'THUA'}**!")

@bot.command()
async def cau(ctx):
    pts = history_cau[-15:]
    graph = "```\n" + "\n".join([f"{l:02}|" + "".join(["●" if abs(p-l)<1 else "──" for p in pts]) for l in range(18, 2, -2)]) + "```"
    await ctx.send(embed=discord.Embed(title="📊 SOI CẦU VERDICT", description=graph, color=0xf1c40f))

# ================= VÍ & SCOREBOARD =================

@bot.command()
async def vi(ctx):
    res = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = res['coins'] if res else 0
    view = ui.View()
    view.add_item(ui.Button(label="Lịch sử", style=discord.ButtonStyle.secondary, custom_id="his"))
    view.add_item(ui.Button(label="Shop", style=discord.ButtonStyle.primary, custom_id="shop"))
    await ctx.send(embed=discord.Embed(title="💳 VÍ VERDICT", description=f"Số dư: **{coins:,}** Cash", color=0x2ecc71), view=view)

@tasks.loop(minutes=2)
async def main_loop():
    ch = bot.get_channel(ID_BONG_DA)
    if not ch: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        m_res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = [m for m in m_res.get('matches', []) if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "TIMED", "PAUSED"]][:3]
        
        await ch.purge(limit=5, check=lambda m: m.author == bot.user)
        for m in matches:
            hcap = get_handicap(m['homeTeam']['id'], m['awayTeam']['id'], m['competition']['code'])
            is_locked = m['status'] != "TIMED"
            
            embed = discord.Embed(title=f"🏟️ {m['competition']['name']}", color=0x2b2d31)
            embed.description = (f"**{m['homeTeam']['name']}** vs **{m['awayTeam']['name']}**\n"
                                 f"⚽ Tỉ số: `{m['score']['fullTime']['home'] or 0} - {m['score']['fullTime']['away'] or 0}`\n"
                                 f"⚖️ Kèo: `{hcap:+0.2g}` (Đội nhà)")
            
            class BetBtns(ui.View):
                @ui.button(label="Cược Chủ", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def b1(self, i, b): await i.response.send_modal(BetModal(m['id'], "chu", m['homeTeam']['shortName'], hcap))
                @ui.button(label="Cược Khách", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def b2(self, i, b): await i.response.send_modal(BetModal(m['id'], "khach", m['awayTeam']['shortName'], -hcap))
            
            await ch.send(embed=embed, view=BetBtns() if not is_locked else None)
    except: pass

@tasks.loop(minutes=10)
async def reward_system():
    pending = query_db("SELECT * FROM bets WHERE status = 'PENDING'")
    if not pending: return
    headers = {"X-Auth-Token": API_KEY}
    for b in pending:
        r = requests.get(f"https://api.football-data.org/v4/matches/{b['match_id']}", headers=headers).json()
        if r.get('status') == 'FINISHED':
            h, a = r['score']['fullTime']['home'], r['score']['fullTime']['away']
            res = (h + b['handicap'] - a) if b['side'] == "chu" else (a + b['handicap'] - h)
            if res > 0: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(b['amount']*1.95), b['user_id']))
            query_db("UPDATE bets SET status = 'DONE' WHERE id = ?", (b['id'],))

@tasks.loop(minutes=30)
async def bxh_update():
    ch = bot.get_channel(ID_BXH)
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    desc = "\n".join([f"**#{i+1}** <@{r['user_id']}>: `{r['coins']:,}` Cash" for i, r in enumerate(top)])
    await ch.purge(limit=1); await ch.send(embed=discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT ✨", description=desc, color=0xffd700))

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    main_loop.start(); reward_system.start(); bxh_update.start()
    print("🚀 VERDICT SYSTEM ONLINE!")

bot.run(TOKEN)
