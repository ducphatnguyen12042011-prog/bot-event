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

def get_match_minute(utc_date_str, status):
    if status != "IN_PLAY": return None
    try:
        start = parse_utc(utc_date_str)
        now = datetime.now(timezone.utc)
        minute = int((now - start).total_seconds() / 60)
        if minute < 1: return 1
        if 45 < minute < 50: return "45+"
        if minute > 90: return "90+"
        return minute
    except: return "?"

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

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

# ================= 🎲 MINI GAME: TÀI XỈU (53% THUA) =================

class TaiXiuModal(ui.Modal, title='🎲 TÀI XỈU VERDICT'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Nhập từ 10k đến 5M...')
    def __init__(self, choice):
        super().__init__()
        self.choice = choice # "Tài" hoặc "Xỉu"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000 or val > 5000000:
                return await interaction.response.send_message("❌ Mức cược: 10,000 - 5,000,000 Cash!", ephemeral=True)

            u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not u or u['coins'] < val:
                return await interaction.response.send_message("❌ Bạn không đủ Cash!", ephemeral=True)

            # Tính toán kết quả: 53% Thua, 47% Thắng
            is_win = random.random() > 0.53
            dice1, dice2, dice3 = random.randint(1,6), random.randint(1,6), random.randint(1,6)
            total = dice1 + dice2 + dice3
            
            # Ép kết quả nếu cần để khớp tỉ lệ
            real_result = "Tài" if total >= 11 else "Xỉu"
            if is_win and real_result != self.choice:
                total = 11 if self.choice == "Tài" else 4 # Ép thắng
            elif not is_win and real_result == self.choice:
                total = 4 if self.choice == "Tài" else 11 # Ép thua

            final_result = "Tài" if total >= 11 else "Xỉu"
            
            if is_win:
                query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (val, interaction.user.id))
                color, msg = 0x2ecc71, "🎉 BẠN ĐÃ THẮNG"
            else:
                query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
                color, msg = 0xe74c3c, "💀 BẠN ĐÃ THUA"

            embed = discord.Embed(title=f"{msg} ({self.choice})", color=color)
            embed.description = f"🎲 Kết quả: **{total} điểm ({final_result})**\n💰 Số tiền: `{val:,}` Cash"
            embed.set_footer(text="Tỉ lệ hoàn vốn: x2.0")
            await interaction.response.send_message(embed=embed)
        except:
            await interaction.response.send_message("❌ Lỗi dữ liệu!", ephemeral=True)

@bot.command()
async def taixiu(ctx):
    embed = discord.Embed(title="🎲 SÒNG BẠC TÀI XỈU", description="Chọn **Tài (11-18)** hoặc **Xỉu (3-10)**\n💰 Cược 1 ăn 2 (Tỉ lệ nhà cái 53%)", color=0x9b59b6)
    view = ui.View()
    view.add_item(ui.Button(label="Tài", style=discord.ButtonStyle.success, custom_id="tx_tai"))
    view.add_item(ui.Button(label="Xỉu", style=discord.ButtonStyle.danger, custom_id="tx_xiu"))
    await ctx.send(embed=embed, view=view)

# ================= 🏟️ SCOREBOARD & BÓNG ĐÁ =================

class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC VERDICT'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Nhập từ 10k đến 5M...')
    def __init__(self, m_id, side, team, hcap):
        super().__init__(); self.m_id=m_id; self.side=side; self.team=team; self.hcap=hcap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000 or val > 5000000:
                return await interaction.response.send_message("❌ Mức cược: 10,000 - 5,000,000 Cash!", ephemeral=True)

            u = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
            if not u or u['coins'] < val: return await interaction.response.send_message("❌ Không đủ tiền!", ephemeral=True)
            
            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status) VALUES (?,?,?,?,?,'PENDING')", (interaction.user.id, self.m_id, self.side, val, self.hcap))
            
            # Gửi vé về DM
            ticket = discord.Embed(title="🎫 VÉ CƯỢC XÁC NHẬN", color=0x3498db, timestamp=datetime.now())
            ticket.add_field(name="🏟️ Trận", value=f"#{self.m_id}", inline=True)
            ticket.add_field(name="🚩 Đội", value=self.team, inline=True)
            ticket.add_field(name="⚖️ Kèo", value=f"{self.hcap:+0.2g}", inline=True)
            ticket.add_field(name="💰 Tiền", value=f"{val:,} Cash", inline=True)
            try: await interaction.user.send(embed=ticket)
            except: pass

            await interaction.response.send_message(f"✅ Đã đặt cược thành công! Check DM để xem vé.", ephemeral=True)
        except: await interaction.response.send_message("❌ Lỗi cược!", ephemeral=True)

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
            color = 0xff4757 if m['status'] == "IN_PLAY" else 0x2f3542
            
            embed = discord.Embed(title=f"🏆 {m['competition']['name'].upper()}", color=color)
            embed.description = (
                f"🕒 **{vn_time(m['utcDate'])}**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏠 **{m['homeTeam']['name']}**: `{m['score']['fullTime']['home'] or 0}`\n"
                f"✈️ **{m['awayTeam']['name']}**: `{m['score']['fullTime']['away'] or 0}`\n\n"
                f"⚖️ **KÈO CHẤP**: {m['homeTeam']['shortName']} `{hcap:+0.2g}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            embed.set_footer(text=f"🆔 ID: {m['id']} • Hệ thống Verdict Master")

            class ActionBtns(ui.View):
                @ui.button(label=f"Cược {m['homeTeam']['shortName']}", style=discord.ButtonStyle.primary, disabled=is_locked)
                async def c1(self, i, b): await i.response.send_modal(BetModal(m['id'], "chu", m['homeTeam']['name'], hcap))
                @ui.button(label=f"Cược {m['awayTeam']['shortName']}", style=discord.ButtonStyle.danger, disabled=is_locked)
                async def c2(self, i, b): await i.response.send_modal(BetModal(m['id'], "khach", m['awayTeam']['name'], -hcap))
            
            await ch.send(embed=embed, view=ActionBtns() if not is_locked else None)
    except: pass

# ================= ⚙️ CORE SYSTEM =================

@bot.event
async def on_interaction(interaction):
    if interaction.type == discord.InteractionType.component:
        cid = interaction.data['custom_id']
        if cid == "tx_tai": await interaction.response.send_modal(TaiXiuModal("Tài"))
        if cid == "tx_xiu": await interaction.response.send_modal(TaiXiuModal("Xỉu"))
        if cid == "shop_open": await interaction.response.send_message("🛒 Shop đang bảo trì!", ephemeral=True)

@bot.command()
async def nap(ctx, user: discord.Member, amt: int):
    if ctx.author.guild_permissions.administrator:
        query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
        await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT)')
    query_db('CREATE TABLE IF NOT EXISTS custom_hcap (match_id INTEGER PRIMARY KEY, hcap REAL)')
    update_scoreboard.start()
    print(f"🚀 {bot.user.name} ONLINE!")

bot.run(TOKEN)
