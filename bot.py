import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone

# --- CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BXH = 1474674662792232981         
ID_BONG_DA = 1474672512708247582     

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ================= 1. HỆ THỐNG VÍ & LỊCH SỬ & SHOP =================
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @ui.button(label="📜 Lịch sử cược", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, button: ui.Button):
        bets = query_db("SELECT match_id, side, amount, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        if not bets: return await interaction.response.send_message("Bạn chưa có lịch sử cược nào.", ephemeral=True)
        
        msg = "🏟️ **LỊCH SỬ 5 TRẬN GẦN NHẤT**\n"
        for m_id, side, amt, status in bets:
            msg += f"• Trận `{m_id}` | {side.upper()} | `{amt:,}` | Kết quả: **{status}**\n"
        await interaction.response.send_message(msg, ephemeral=True)

    @ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.success)
    async def deposit(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Để nạp tiền, vui lòng chuyển khoản qua STK: `123456789` (Nội dung: Tên Discord) hoặc liên hệ Admin.", ephemeral=True)

    @ui.button(label="🛒 Shop Vật Phẩm", style=discord.ButtonStyle.primary)
    async def shop(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(title="🛒 VERDICT SHOP", description="Dùng Cash để đổi các vật phẩm đặc biệt!", color=0xe91e63)
        embed.add_field(name="1. Thẻ Đổi Tên (50,000 Cash)", value="Dùng lệnh: `!mua 1`", inline=False)
        embed.add_field(name="2. Role 'Đại Gia' 7 ngày (500,000 Cash)", value="Dùng lệnh: `!mua 2`", inline=False)
        embed.add_field(name="3. Cúp Vàng Profile (1,000,000 Cash)", value="Dùng lệnh: `!mua 3`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ TIỀN CỦA BẠN", description=f"Chào **{ctx.author.name}**,\nSố dư hiện tại: **{coins:,}** Cash", color=0x2ecc71)
    embed.set_thumbnail(url=ctx.author.avatar.url)
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
async def mua(ctx, item_id: int):
    items = {1: ("Thẻ Đổi Tên", 50000), 2: ("Role Đại Gia", 500000), 3: ("Cúp Vàng", 1000000)}
    if item_id not in items: return await ctx.send("❌ ID vật phẩm không tồn tại!")
    name, price = items[item_id]
    
    user_coins = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_coins or user_coins[0] < price: return await ctx.send("❌ Bạn không đủ Cash!")
    
    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, ctx.author.id))
    await ctx.send(f"✅ Bạn đã mua thành công **{name}**. Vui lòng liên hệ Admin để nhận quà!")

# ================= 2. MODAL CƯỢC & KÈO CHẤP AI =================
def calculate_handicap(h_rank, a_rank):
    if not h_rank or not a_rank: return 0.0
    diff = a_rank - h_rank
    return round((diff / 2) * 0.25 * 4) / 4

class CuocModal(ui.Modal, title='🎰 PHIẾU CƯỢC BÓNG ĐÁ'):
    amount = ui.TextInput(label='Số tiền cược', placeholder='Ví dụ: 100000', min_length=1)
    def __init__(self, match_id, side, team_name, handicap):
        super().__init__()
        self.match_id, self.side, self.team_name, self.handicap = match_id, side, team_name, handicap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            user_coins = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not user_coins or user_coins[0] < val: return await interaction.response.send_message("❌ Không đủ tiền!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
                     (interaction.user.id, self.match_id, self.side, val, self.handicap))

            # GỬI VÉ QUA DM
            embed_dm = discord.Embed(title="🎫 VÉ CƯỢC HÀNG QUÂN", color=0x3498db, timestamp=datetime.now())
            embed_dm.add_field(name="🛡️ Đội chọn", value=self.team_name, inline=True)
            embed_dm.add_field(name="📊 Kèo chấp", value=f"{self.handicap:+}", inline=True)
            embed_dm.add_field(name="💰 Tiền cược", value=f"{val:,} Cash", inline=False)
            embed_dm.set_footer(text=f"ID Trận: {self.match_id}")
            
            await interaction.user.send(embed=embed_dm)
            await interaction.response.send_message(f"✅ Cược thành công! Vé đã gửi vào DM của bạn.", ephemeral=True)
        except: await interaction.response.send_message("❌ Lỗi hệ thống!", ephemeral=True)

# ================= 3. GIAO DIỆN TỈ SỐ & TRẢ THƯỞNG =================
@tasks.loop(minutes=2)
async def bongda_update():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        std = requests.get("https://api.football-data.org/v4/competitions/PL/standings", headers={"X-Auth-Token": API_KEY}).json()
        ranks = {s['team']['id']: s['position'] for s in std['standings'][0]['table']}
        
        matches = [m for m in res.get('matches', []) if m['status'] in ["IN_PLAY", "TIMED", "LIVE"]][:3]
        await channel.purge(limit=5, check=lambda m: m.author == bot.user)

        for m in matches:
            h_rank, a_rank = ranks.get(m['homeTeam']['id'], 10), ranks.get(m['awayTeam']['id'], 10)
            h_handicap = calculate_handicap(h_rank, a_rank)
            diff = (datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds() / 60
            is_locked = m['status'] != "TIMED" or diff <= 15

            embed = discord.Embed(title=f"🏟️ {m['competition']['name']}", color=0x2b2d31)
            embed.add_field(name="Đội bóng", value=f"🛡️ **{m['homeTeam']['shortName']}**\n🛡️ **{m['awayTeam']['shortName']}**", inline=True)
            embed.add_field(name="Tỉ số / Kèo", value=f"**{m['score']['fullTime']['home'] or 0}** (Chấp {h_handicap:+})\n**{m['score']['fullTime']['away'] or 0}**", inline=True)
            embed.set_thumbnail(url=m['homeTeam'].get('crest'))
            
            class BetBtns(ui.View):
                @ui.button(label="Cược Chủ", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def b1(self, i, b): await i.response.send_modal(CuocModal(m['id'], "chu", m['homeTeam']['shortName'], h_handicap))
                @ui.button(label="Cược Khách", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def b2(self, i, b): await i.response.send_modal(CuocModal(m['id'], "khach", m['awayTeam']['shortName'], -h_handicap))

            await channel.send(embed=embed, view=BetBtns() if not is_locked else None)
    except: pass

@tasks.loop(minutes=10)
async def auto_reward():
    pending = query_db("SELECT id, user_id, match_id, side, amount, handicap FROM bets WHERE status = 'PENDING'")
    for b_id, u_id, m_id, side, amt, hcap in pending:
        try:
            r = requests.get(f"https://api.football-data.org/v4/matches/{m_id}", headers={"X-Auth-Token": API_KEY}).json()
            if r.get('status') == 'FINISHED':
                h, a = r['score']['fullTime']['home'], r['score']['fullTime']['away']
                res_val = (h + hcap - a) if side == "chu" else (a + hcap - h)
                status = "WIN" if res_val > 0 else ("DRAW" if res_val == 0 else "LOSE")
                
                if status == "WIN": query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(amt * 1.95), u_id))
                elif status == "DRAW": query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, u_id))
                
                query_db("UPDATE bets SET status = ? WHERE id = ?", (status, b_id))
                u = await bot.fetch_user(u_id)
                await u.send(f"🔔 Trận `{m_id}` kết thúc: **{status}**. Số dư đã cập nhật!")
        except: continue

# ================= 4. TÀI XỈU 47% & SOI CẦU LƯỚI =================
history_points = []
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_points
    side = side.lower()
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Không đủ tiền!")

    win = random.randint(1, 100) <= 47
    d1, d2, d3 = [random.randint(1, 6) for _ in range(3)]
    total = d1+d2+d3
    res = "tai" if total >= 11 else "xiu"
    
    if (win and res != side) or (not win and res == side):
        total = random.randint(11,18) if side == "tai" and win else random.randint(3,10)
        d1 = random.randint(1, min(6, total-2)); d2 = random.randint(1, min(6, total-d1-1)); d3 = total-d1-d2
        res = "tai" if total >= 11 else "xiu"

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount if side == res else -amount, ctx.author.id))
    history_points.append(total)

    embed = discord.Embed(title="🎲 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if side == res else 0xff4d4d)
    embed.add_field(name="Xúc xắc", value=f"{d1} - {d2} - {d3}", inline=False)
    embed.add_field(name="Tổng điểm", value=f"**{total}** ({res.upper()})", inline=True)
    embed.add_field(name="Kết quả", value=f"**{'THẮNG' if side == res else 'THUA'}**", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def cau(ctx):
    pts = history_points[-20:]
    graph = "```\n"
    for lvl in range(18, 2, -2):
        graph += f"{lvl:02} |" + "".join([" ● " if abs(p-lvl) < 1 else " ── " for p in pts]) + "\n"
    await ctx.send(embed=discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU", description=graph + "```", color=0xf1c40f))

# ================= 5. KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    bongda_update.start(); auto_reward.start(); 
    print("🚀 VERDICT ULTIMATE SYSTEM ONLINE!")

bot.run(TOKEN)
