import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta
from dateutil import parser

# --- CẤU HÌNH HỆ THỐNG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582 # Channel Kèo & Tỉ số
ID_BXH = 1474674662792232981     # Channel BXH Đại Gia
ALLOWED_LEAGUES = ['PL', 'PD', 'CL'] # Ngoại hạng Anh, La Liga, Cúp C1

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
def get_match_minute(utc_date_str, status):
    if status != "IN_PLAY": return None
    try:
        start = parser.parse(utc_date_str)
        now = datetime.now(timezone.utc)
        minute = int((now - start).total_seconds() / 60)
        if minute < 1: return 1
        if 45 < minute < 50: return "45+"
        if minute > 90: return "90+"
        return minute
    except: return "?"

def get_smart_hcap(m):
    try:
        headers = {"X-Auth-Token": API_KEY}
        url = f"https://api.football-data.org/v4/competitions/{m['competition']['code']}/standings"
        res = requests.get(url, headers=headers, timeout=5).json()
        ranks = {t['team']['id']: t['position'] for st in res['standings'] if st['type']=='TOTAL' for t in st['table']}
        diff = ranks.get(m['awayTeam']['id'], 10) - ranks.get(m['homeTeam']['id'], 10)
        return round((diff / 4) * 0.25 * 4) / 4
    except: return 0.0

def vn_time(utc_str):
    dt = parser.parse(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

# ================= ✨ BẢNG XẾP HẠNG SANG TRỌNG ✨ =================

@tasks.loop(minutes=30)
async def update_bxh():
    ch = bot.get_channel(ID_BXH)
    if not ch: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    embed = discord.Embed(
        title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨",
        description="Những phú hào sở hữu khối tài sản lớn nhất hệ thống.\n" + "━" * 15,
        color=0xffd700,
        timestamp=datetime.now()
    )
    
    medals = ["🥇", "🥈", "🥉", "👤", "👤", "👤", "👤", "👤", "👤", "👤"]
    lb_text = ""
    for i, r in enumerate(top):
        lb_text += f"{medals[i]} `#{i+1:02}` <@{r['user_id']}> — **{r['coins']:,}** Cash\n"
    
    embed.add_field(name="Danh sách triệu phú", value=lb_text or "Chưa có dữ liệu", inline=False)
    embed.set_footer(text="Tự động cập nhật mỗi 30 phút")
    
    await ch.purge(limit=5, check=lambda m: m.author == bot.user)
    await ch.send(embed=embed)

# ================= 🏟️ SCOREBOARD (PHÚT ĐÁ & TRẠNG THÁI) =================

@tasks.loop(minutes=2)
async def update_scoreboard():
    ch = bot.get_channel(ID_BONG_DA)
    if not ch: return
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        active = [m for m in res.get('matches', []) if m['competition']['code'] in ALLOWED_LEAGUES and m['status'] in ["IN_PLAY", "TIMED", "PAUSED", "LIVE"]][:5]
        
        await ch.purge(limit=10, check=lambda m: m.author == bot.user)
        for m in active:
            hcap = get_smart_hcap(m)
            minute = get_match_minute(m['utcDate'], m['status'])
            is_locked = m['status'] != "TIMED"
            
            if m['status'] == "IN_PLAY":
                status_txt = f"🔴 ĐANG ĐÁ: Phút {minute}'"
                color = 0xe74c3c
            elif m['status'] == "PAUSED":
                status_txt = "☕ NGHỈ HIỆP"
                color = 0xf1c40f
            else:
                status_txt = f"🕒 SẮP ĐÁ: {vn_time(m['utcDate'])}"
                color = 0x2b2d31

            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=color)
            score_h = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
            score_a = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0

            embed.description = (
                f"**{status_txt}**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏠 **{m['homeTeam']['name']}**\n"
                f"╰ Tỉ số: `{score_h}` — Chấp: `{hcap:+0.2g}`\n\n"
                f"✈️ **{m['awayTeam']['name']}**\n"
                f"╰ Tỉ số: `{score_a}` — Kèo: `0` (Ăn đủ)\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 ID Trận: {m['id']}"
            )

            class ActionBtns(ui.View):
                @ui.button(label=f"Cược {m['homeTeam']['shortName']}", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def c1(self, i, b): await i.response.send_modal(BetModal(m['id'], "chu", m['homeTeam']['name'], hcap))
                @ui.button(label=f"Cược {m['awayTeam']['shortName']}", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def c2(self, i, b): await i.response.send_modal(BetModal(m['id'], "khach", m['awayTeam']['name'], -hcap))
            
            await ch.send(embed=embed, view=ActionBtns() if not is_locked else None)
    except: pass

# ================= 💰 HỆ THỐNG TRẢ THƯỞNG TỰ ĐỘNG =================

@tasks.loop(minutes=10)
async def auto_payout():
    pending = query_db("SELECT * FROM bets WHERE status = 'PENDING'")
    if not pending: return
    headers = {"X-Auth-Token": API_KEY}
    for b in pending:
        try:
            r = requests.get(f"https://api.football-data.org/v4/matches/{b['match_id']}", headers=headers).json()
            if r.get('status') == 'FINISHED':
                h = r['score']['fullTime']['home']
                a = r['score']['fullTime']['away']
                
                # Tính kết quả
                if b['side'] == "chu":
                    result = (h + b['handicap']) - a
                else:
                    result = (a + b['handicap']) - h

                if result > 0: # Thắng (x1.95)
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(b['amount']*1.95), b['user_id']))
                    msg, color = "🎉 Bạn đã THẮNG", 0x2ecc71
                elif result == 0: # Hòa (Hoàn tiền)
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (b['amount'], b['user_id']))
                    msg, color = "⚖️ Bạn đã HÒA KÈO", 0x3498db
                else:
                    msg, color = "💀 Bạn đã THUA", 0xe74c3c

                query_db("UPDATE bets SET status = 'DONE' WHERE id = ?", (b['id'],))
                
                # Gửi thông báo kết quả DM
                try:
                    user = await bot.fetch_user(b['user_id'])
                    emb = discord.Embed(title="🔔 KẾT QUẢ KÈO", description=f"{msg}\nTiền cược: `{b['amount']:,}` Cash", color=color)
                    await user.send(embed=emb)
                except: pass
        except: continue

# ================= 🛒 SHOP TICKET & VÍ =================

class ShopView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    async def create_ticket(self, interaction, item, price):
        u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not u or u['coins'] < price: return await interaction.response.send_message("❌ Không đủ Cash!", ephemeral=True)
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        cat = discord.utils.get(interaction.guild.categories, name="TICKETS")
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        channel = await interaction.guild.create_text_channel(name=f"🛒-{item}", category=cat, overwrites=overwrites)
        await channel.send(f"📦 {interaction.user.mention} đã đổi **{item}**. Chờ Admin!")
        await interaction.response.send_message(f"✅ Đã tạo Ticket mua hàng: {channel.mention}", ephemeral=True)

    @ui.button(label="Thẻ Đổi Tên (50k)", style=discord.ButtonStyle.success, emoji="🏷️")
    async def b1(self, i, b): await self.create_ticket(i, "The-Doi-Ten", 50000)

@bot.command()
async def vi(ctx):
    u = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = u['coins'] if u else 0
    view = ui.View()
    view.add_item(ui.Button(label="Mở Shop", style=discord.ButtonStyle.success, custom_id="shop_open"))
    embed = discord.Embed(title="💳 VÍ VERDICT", description=f"Thành viên: {ctx.author.mention}\nSố dư: **{coins:,}** Cash", color=0x2ecc71)
    await ctx.send(embed=embed, view=view)

# ================= VẬN HÀNH =================

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC VERDICT'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Nhập số Cash...')
    def __init__(self, m_id, side, team, hcap):
        super().__init__(); self.m_id=m_id; self.side=side; self.team=team; self.hcap=hcap
    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not u or u['coins'] < val: return await interaction.response.send_message("❌ Không đủ tiền!", ephemeral=True)
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (interaction.user.id, self.m_id, self.side, val, self.hcap))
            
            emb = discord.Embed(title="✅ VÉ CƯỢC XÁC NHẬN", color=0x2ecc71)
            emb.description = f"🏟️ **Trận**: {self.team}\n⚖️ **Kèo**: `{self.hcap:+}`\n💰 **Cược**: `{val:,}` Cash"
            try: await interaction.user.send(embed=emb)
            except: pass
            await interaction.response.send_message("✅ Đã đặt cược thành công!", ephemeral=True)
        except: await interaction.response.send_message("❌ Lỗi dữ liệu!", ephemeral=True)

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.event
async def on_interaction(interaction):
    if interaction.type == discord.InteractionType.component and interaction.data['custom_id'] == "shop_open":
        await interaction.response.send_message("🛒 Cửa hàng Verdict Cash", view=ShopView(), ephemeral=True)

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    update_scoreboard.start()
    update_bxh.start()
    auto_payout.start() # Kích hoạt trả thưởng tự động
    print(f"🚀 {bot.user.name} ONLINE - HỆ THỐNG TRẢ THƯỞNG ĐÃ BẬT!")

bot.run(TOKEN)
