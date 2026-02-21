import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# ================= CẤU HÌNH =================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582
ID_BXH = 1474674662792232981
ADMIN_ROLES = [1465374336214106237]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================= DATABASE =================
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ================= GIAO DIỆN CƯỢC =================
class BetModal(ui.Modal, title='🎫 XÁC NHẬN TIỀN CƯỢC'):
    amount = ui.TextInput(label='Nhập số xu ảo (Ví dụ: 1000)', min_length=1, placeholder="Tối thiểu 100 xu...")

    def __init__(self, match_id, team, hdp):
        super().__init__()
        self.match_id, self.team, self.hdp = match_id, team, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            if val < 100: raise ValueError
        except: return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

        user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user or user[0] < val: return await interaction.response.send_message("❌ Bạn không đủ xu!", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, ?, ?, ?, ?, 'PENDING')", 
                 (interaction.user.id, self.match_id, val, self.team, self.hdp))
        await interaction.response.send_message(f"✅ Đã đặt **{val:,}** xu cho đội **{self.team}**", ephemeral=True)

class FootballView(ui.View):
    def __init__(self, match_id, h_name, a_name, hdp):
        super().__init__(timeout=None)
        self.match_id, self.h_name, self.a_name, self.hdp = match_id, h_name, a_name, hdp

    @ui.button(label="Cược Chủ Nhà", style=discord.ButtonStyle.success, emoji="🏠")
    async def bet_h(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BetModal(self.match_id, self.h_name, self.hdp))

    @ui.button(label="Cược Đội Khách", style=discord.ButtonStyle.danger, emoji="✈️")
    async def bet_a(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BetModal(self.match_id, self.a_name, -self.hdp))

# ================= TỰ ĐỘNG CẬP NHẬT TRẬN ĐẤU =================
@tasks.loop(minutes=15)
async def update_matches():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:5]
        await channel.purge(limit=15, check=lambda m: m.author == bot.user)

        for m in matches:
            h_team, a_team = m['homeTeam'], m['awayTeam']
            hdp = 0.5 
            
            # Giao diện mới: Logo ở trên cùng
            embed = discord.Embed(color=0x2b2d31)
            embed.set_author(name=f"TRẬN ĐẤU: {h_team['name']} vs {a_team['name']}", icon_url=h_team.get('crest'))
            embed.set_thumbnail(url=a_team.get('crest'))
            
            embed.description = (
                f"### 🏟️ Giải đấu: {m['competition']['name']}\n"
                f"📊 **Tỉ số:** `{m['score']['fullTime']['home'] or 0} - {m['score']['fullTime']['away'] or 0}`\n"
                f"⏰ **Bắt đầu:** <t:{int(datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ').timestamp())}:F>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⚖️ **KÈO CHẤP:** Chủ nhà chấp `{hdp}`\n"
                f"💰 **Tỉ lệ thưởng:** 1 ăn 1 (Hoàn tiền + Thưởng)\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await channel.send(embed=embed, view=FootballView(m['id'], h_team['name'], a_team['name'], hdp))
    except: pass

# ================= TỰ ĐỘNG TRẢ THƯỞNG =================
@tasks.loop(minutes=30)
async def settlement():
    pending = query_db("SELECT DISTINCT match_id FROM bets WHERE status = 'PENDING'")
    if not pending or not API_KEY: return

    for (m_id,) in pending:
        try:
            res = requests.get(f"https://api.football-data.org/v4/matches/{m_id}", headers={"X-Auth-Token": API_KEY}).json()
            if res.get('status') == 'FINISHED':
                h_score = res['score']['fullTime']['home']
                a_score = res['score']['fullTime']['away']
                
                bets = query_db("SELECT id, user_id, amount, team, hdp FROM bets WHERE match_id = ? AND status = 'PENDING'", (m_id,))
                for b_id, u_id, amt, team, hdp in bets:
                    is_home = (team == res['homeTeam']['name'])
                    win = (h_score + hdp > a_score) if is_home else (a_score + hdp > h_score)
                    
                    if win:
                        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt * 2, u_id))
                    query_db("UPDATE bets SET status = 'DONE' WHERE id = ?", (b_id,))
        except: continue

# ================= BẢNG XẾP HẠNG ĐẸP =================
@tasks.loop(minutes=20)
async def update_lb():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    embed = discord.Embed(title="🏆 BẢNG VINH DANH ĐẠI GIA COIN ẢO", color=0xffd700)
    embed.set_thumbnail(url="https://i.imgur.com/vHqB7Y8.png") # Link icon Cup xịn
    
    lb_content = ""
    for i, (uid, coins) in enumerate(top, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**#{i}**"
        lb_content += f"{medal} <@{uid}> — `{coins:,}` xu\n"
        lb_content += "----------------------------------\n"

    embed.description = lb_content if lb_content else "Chưa có dữ liệu người chơi."
    embed.set_footer(text="Cập nhật tự động mỗi 20 phút")
    
    await channel.purge(limit=2)
    await channel.send(embed=embed)

# ================= LỆNH CƠ BẢN =================
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ TIỀN", description=f"Chào {ctx.author.mention}, bạn đang có:\n## `{coins:,}` xu ảo", color=0x3498db)
    await ctx.send(embed=embed)

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu cho {member.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    update_matches.start()
    update_lb.start()
    settlement.start()
    print(f"🚀 Bot {bot.user} đã sẵn sàng trên Railway!")

bot.run(TOKEN)
