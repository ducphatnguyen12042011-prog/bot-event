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
ID_BONG_DA = 1474672512708247582 # Channel kèo
ID_BXH = 1474674662792232981    # Channel BXH
ALLOWED_LEAGUES = ['PL', 'PD', 'CL']

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('verdict.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        return (res[0] if res and one else res)
    finally:
        conn.close()

# --- LOGIC KÈO & THỜI GIAN ---
def get_smart_hcap(m):
    try:
        headers = {"X-Auth-Token": API_KEY}
        l_code = m['competition']['code']
        url = f"https://api.football-data.org/v4/competitions/{l_code}/standings"
        res = requests.get(url, headers=headers).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        diff = ranks.get(m['awayTeam']['id'], 10) - ranks.get(m['homeTeam']['id'], 10)
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.0

def vn_time(utc_str):
    dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

# ================= UI: VÉ CƯỢC & MODAL =================
class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC VERDICT'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Nhập số Cash...')
    def __init__(self, m_id, side, team, hcap):
        super().__init__(); self.m_id=m_id; self.side=side; self.team=team; self.hcap=hcap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not user or user['coins'] < val: return await interaction.response.send_message("❌ Bạn không đủ Cash!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')",
                     (interaction.user.id, self.m_id, self.side, val, self.hcap))
            
            # Gửi vé qua DM
            embed = discord.Embed(title="✅ XÁC NHẬN VÉ CƯỢC", color=0x2ecc71, timestamp=datetime.now())
            embed.description = f"🏟️ **Trận ID**: `{self.m_id}`\n🚩 **Chọn**: {self.team}\n⚖️ **Kèo**: `{self.hcap:+}`\n💰 **Tiền**: `{val:,}` Cash"
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("✅ Đã đặt cược! Kiểm tra DM để xem vé.", ephemeral=True)
        except: await interaction.response.send_message("❌ Lỗi: Vui lòng nhập số nguyên.", ephemeral=True)

# ================= SHOP TICKET & ITEM =================
class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    async def buy_process(self, interaction, item_name, price):
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not u or u['coins'] < price: return await interaction.response.send_message("❌ Không đủ Cash!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name="TICKETS")
        overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        channel = await guild.create_text_channel(name=f"🛒-{item_name}", category=category, overwrites=overwrites)
        await channel.send(f"📦 {interaction.user.mention} đã đổi **{item_name}**. Vui lòng chờ Admin xử lý!")
        await interaction.response.send_message(f"✅ Đã tạo Ticket: {channel.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.success, emoji="🏷️")
    async def buy1(self, i, b): await self.buy_process(i, "The-Doi-Ten", 50000)

# ================= TÀI XỈU 53% & SOI CẦU =================
tx_history = []

@bot.command()
async def taixiu(ctx, lua_chon: str, tien: int):
    global tx_history
    lua_chon = lua_chon.lower()
    user = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user or user['coins'] < tien: return await ctx.send("❌ Bạn không đủ tiền!")

    # Tỉ lệ thua 53% (Thắng 47%)
    is_win = random.random() < 0.47
    dice = [random.randint(1,6) for _ in range(3)]
    total = sum(dice)
    result = "tai" if total >= 11 else "xiu"

    if (is_win and result != lua_chon) or (not is_win and result == lua_chon):
        total = random.randint(11,17) if lua_chon == "tai" and is_win else random.randint(4,10)
        result = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (tien if lua_chon==result else -tien, ctx.author.id))
    tx_history.append(total)
    
    embed = discord.Embed(title="🎲 KẾT QUẢ TÀI XỈU", color=0xf1c40f if lua_chon==result else 0xe74c3c)
    embed.description = f"Số: **{total}** ({result.upper()})\nBạn: **{'THẮNG' if lua_chon==result else 'THUA'}** `{tien:,}` Cash"
    await ctx.send(embed=embed)

@bot.command()
async def cau(ctx):
    pts = tx_history[-15:]
    if not pts: return await ctx.send("Chưa có dữ liệu cầu!")
    graph = "```\n" + "\n".join([f"{l:02}| " + "".join(["● " if p==l else "──" for p in pts]) for l in range(18, 2, -1)]) + "\n    " + "--"*len(pts) + "```"
    await ctx.send(embed=discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU", description=graph, color=0x3498db))

# ================= HỆ THỐNG CHÍNH =================
@tasks.loop(minutes=2)
async def update_matches():
    ch = bot.get_channel(ID_BONG_DA)
    if not ch: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        active = [m for m in res['matches'] if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "TIMED", "PAUSED", "LIVE"]][:5]
        
        await ch.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in active:
            hcap = get_smart_hcap(m)
            is_locked = m['status'] != "TIMED"
            
            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=0x2b2d31)
            embed.description = (f"⏰ `{vn_time(m['utcDate'])}` VN\n\n"
                                 f"🏠 **{m['homeTeam']['name']}** `{m['score']['fullTime']['home'] or 0}`\n"
                                 f"✈️ **{m['awayTeam']['name']}** `{m['score']['fullTime']['away'] or 0}`\n\n"
                                 f"⚖️ Kèo: `{hcap:+0.2g}` (Chủ chấp)\n"
                                 f"━━━━━━━━━━━━━━━━━━━━\n"
                                 f"📢 **{m['status']}**")
            
            class ActionBtns(ui.View):
                @ui.button(label="Cược Chủ", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def c1(self, i, b): await i.response.send_modal(BetModal(m['id'], "chu", m['homeTeam']['name'], hcap))
                @ui.button(label="Cược Khách", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def c2(self, i, b): await i.response.send_modal(BetModal(m['id'], "khach", m['awayTeam']['name'], -hcap))
            
            await ch.send(embed=embed, view=ActionBtns() if not is_locked else None)
    except: pass

@tasks.loop(minutes=30)
async def update_bxh():
    ch = bot.get_channel(ID_BXH)
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    desc = "\n".join([f"**#{i+1}** <@{r['user_id']}> — `{r['coins']:,}` Cash" for i, r in enumerate(top)])
    await ch.purge(limit=1)
    await ch.send(embed=discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", description=desc, color=0xffd700))

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = u['coins'] if u else 0
    view = ui.View()
    view.add_item(ui.Button(label="Lịch sử cược", style=discord.ButtonStyle.secondary, custom_id="history"))
    view.add_item(ui.Button(label="Shop Item", style=discord.ButtonStyle.success, custom_id="shop_open"))
    await ctx.send(embed=discord.Embed(title="💳 VÍ VERDICT", description=f"Thành viên: {ctx.author.mention}\nSố dư: **{coins:,}** Cash", color=0x2ecc71), view=view)

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_matches.start(); update_bxh.start()
    print("🚀 VERDICT BOT IS READY!")

bot.run(TOKEN)
