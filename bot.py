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
ID_BXH = 1474674662792232981         
ID_BONG_DA = 1474672512708247582     
ADMIN_ROLE_ID = 123456789012345678  # THAY ID ROLE ADMIN CỦA BẠN

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ENGINE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        if not res: return None
        return (res[0] if one else res)
    finally:
        conn.close()

# ================= 1. MODAL CƯỢC =================
class CuocModal(ui.Modal, title='🎰 PHIẾU CƯỢC BÓNG ĐÁ'):
    amount = ui.TextInput(label='Số tiền cược', placeholder='Nhập số tiền...', min_length=1)
    
    def __init__(self, match_id, side, team_name, handicap):
        super().__init__()
        self.m_id, self.side, self.team, self.hcap = match_id, side, team_name, handicap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not user_data or user_data['coins'] < val:
                return await interaction.response.send_message("❌ Bạn không đủ Cash!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
                     (interaction.user.id, self.m_id, self.side, val, self.hcap))

            emb = discord.Embed(title="🎫 VÉ CƯỢC XÁC NHẬN", color=0x2ecc71)
            emb.add_field(name="🛡️ Đội chọn", value=f"**{self.team}**", inline=True)
            emb.add_field(name="📊 Kèo chấp", value=f"`{self.hcap:+0.2f}`", inline=True)
            emb.add_field(name="💰 Tiền cược", value=f"`{val:,}` Cash", inline=False)
            
            await interaction.user.send(embed=emb)
            await interaction.response.send_message(f"✅ Đã cược thành công! Vé đã được gửi vào DM.", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Vui lòng nhập số hợp lệ!", ephemeral=True)

# ================= 2. SCOREBOARD (GIAO DIỆN THEO YÊU CẦU) =================
def get_ai_handicap(h_rank, a_rank):
    if not h_rank or not a_rank: return 0.0
    diff = a_rank - h_rank
    return round((diff / 2.5) * 0.25 * 4) / 4

@tasks.loop(minutes=2)
async def update_scoreboard():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        std = requests.get("https://api.football-data.org/v4/competitions/PL/standings", headers={"X-Auth-Token": API_KEY}).json()
        ranks = {s['team']['id']: s['position'] for s in std['standings'][0]['table']}
        
        matches = [m for m in res.get('matches', []) if m['status'] in ["IN_PLAY", "TIMED", "LIVE", "PAUSED"]][:3]
        await channel.purge(limit=10, check=lambda m: m.author == bot.user)

        for m in matches:
            h_rank, a_rank = ranks.get(m['homeTeam']['id'], 10), ranks.get(m['awayTeam']['id'], 10)
            h_hcap = get_ai_handicap(h_rank, a_rank)
            
            # Tính thời gian
            status_text = "🕒 Chờ bắt đầu"
            if m['status'] == "IN_PLAY":
                start = datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00'))
                elapsed = int((datetime.now(timezone.utc) - start).total_seconds() / 60)
                status_text = f"⏱️ Phút: {elapsed}'"
            elif m['status'] == "PAUSED":
                status_text = "☕ Nghỉ giải lao"

            diff_start = (datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds() / 60
            is_locked = m['status'] != "TIMED" or diff_start <= 15

            # --- EMBED GIAO DIỆN THEO YÊU CẦU ---
            embed = discord.Embed(color=0x2b2d31)
            embed.set_author(name=f"🏆 {m['competition']['name']} ⸻ Tỉ số: {m['score']['fullTime']['home'] or 0} - {m['score']['fullTime']['away'] or 0}")
            
            embed.description = (
                f"🛡️ **{m['homeTeam']['name']}**\n"
                f"🛡️ **{m['awayTeam']['name']}**\n\n"
                f"**📊 TỈ LỆ KÈO CHẤP:**\n"
                f"• {m['homeTeam']['shortName']}: `{h_hcap:+0.2f}`\n"
                f"• {m['awayTeam']['shortName']}: `0.00`\n\n"
                f"⏱️ **THỜI GIAN:** {status_text}\n"
                f"📌 **TRẠNG THÁI:** {'🔒 ĐÓNG CƯỢC' if is_locked else '✅ ĐANG MỞ'}"
            )
            
            if m['homeTeam'].get('crest'): embed.set_thumbnail(url=m['homeTeam'].get('crest'))

            class BetBtns(ui.View):
                @ui.button(label=f"Cược {m['homeTeam']['shortName']}", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def b1(self, i, b): await i.response.send_modal(CuocModal(m['id'], "chu", m['homeTeam']['shortName'], h_hcap))
                @ui.button(label=f"Cược {m['awayTeam']['shortName']}", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def b2(self, i, b): await i.response.send_modal(CuocModal(m['id'], "khach", m['awayTeam']['shortName'], -h_hcap))

            await channel.send(embed=embed, view=BetBtns() if not is_locked else None)
    except: pass

# ================= 3. LỆNH NẠP & VÍ & SHOP =================
@bot.command()
async def nap(ctx, user: discord.Member, amount: int):
    """Admin dùng lệnh này để nạp tiền cho người chơi"""
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Bạn không có quyền dùng lệnh này!")
    
    query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amount, amount))
    
    emb = discord.Embed(title="💰 GIAO DỊCH THÀNH CÔNG", color=0x2ecc71)
    emb.add_field(name="Người nhận", value=user.mention)
    emb.add_field(name="Số tiền", value=f"`{amount:,}` Cash")
    await ctx.send(embed=emb)

class ShopView(ui.View):
    async def create_ticket(self, interaction, item, price):
        user = interaction.user
        d = query_db("SELECT coins FROM users WHERE user_id = ?", (user.id,), one=True)
        if not d or d['coins'] < price: return await interaction.response.send_message("❌ Không đủ tiền!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, user.id))
        guild = interaction.guild
        cat = discord.utils.get(guild.categories, name="TICKETS")
        channel = await guild.create_text_channel(f"🎫-{item}-{user.name}", category=cat)
        await channel.set_permissions(user, read_messages=True, send_messages=True)
        await channel.send(f"🛒 {user.mention} đã mua **{item}**. Chờ Admin xử lý!")
        await interaction.response.send_message(f"✅ Đã tạo ticket tại {channel.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.primary)
    async def b1(self, i, b): await self.create_ticket(i, "The-Doi-Ten", 50000)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d['coins'] if d else 0
    emb = discord.Embed(title="💳 VÍ TIỀN VERDICT", description=f"Số dư: **{coins:,}** Cash", color=0x2ecc71)
    
    view = ui.View()
    btn = ui.Button(label="🛒 Mua Sắm", style=discord.ButtonStyle.secondary)
    async def callback(i): await i.response.send_message("Cửa hàng vật phẩm:", view=ShopView(), ephemeral=True)
    btn.callback = callback
    view.add_item(btn)
    await ctx.send(embed=emb, view=view)

# ================= 4. BXH & TÀI XỈU =================
@tasks.loop(minutes=5)
async def update_bxh():
    ch = bot.get_channel(ID_BXH)
    if not ch: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    emb = discord.Embed(title="🏆 BẢNG XẾP HẠNG ĐẠI GIA", color=0xffd700)
    desc = ""
    for i, r in enumerate(top):
        desc += f"**#{i+1}** <@{r['user_id']}> — `{r['coins']:,}` Cash\n"
    emb.description = desc
    await ch.purge(limit=1); await ch.send(embed=emb)

history_points = []
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_points
    side = side.lower()
    user = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user or user['coins'] < amount: return await ctx.send("❌ Không đủ tiền!")

    is_win = random.randint(1, 100) <= 47
    d = [random.randint(1, 6) for _ in range(3)]
    total = sum(d)
    res = "tai" if total >= 11 else "xiu"
    
    if (is_win and res != side) or (not is_win and res == side):
        total = random.randint(11,18) if side == "tai" and is_win else random.randint(3,10)
        d = [random.randint(1, 6), random.randint(1, 6), 0]; d[2] = total - d[0] - d[1] # Cân bằng lại xúc xắc

    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount if side == res else -amount, ctx.author.id))
    history_points.append(total)
    await ctx.send(f"🎲 **{d[0]}-{d[1]}-{d[2]}** ➔ **{total} ({res.upper()})**. Bạn đã **{'THẮNG' if side == res else 'THUA'}**!")

@bot.command()
async def cau(ctx):
    pts = history_points[-20:]
    graph = "```\n"
    for lvl in range(18, 2, -2):
        graph += f"{lvl:02} ┃" + "".join([" ● " if abs(p-lvl) < 1 else " ── " for p in pts]) + "\n"
    await ctx.send(embed=discord.Embed(title="📊 SOI CẦU LƯỚI", description=graph + "```", color=0xf1c40f))

# ================= 5. STARTUP =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start(); update_bxh.start()
    print("🚀 SYSTEM READY!")

bot.run(TOKEN)
