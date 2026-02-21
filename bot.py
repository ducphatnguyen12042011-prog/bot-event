import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

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

# ================= UI: ĐẶT CƯỢC =================
class BetModal(ui.Modal, title='🎫 TIỀN CƯỢC'):
    amount = ui.TextInput(label='Nhập số xu', placeholder='Tối thiểu 100...', min_length=1)

    def __init__(self, match_id, team, hdp):
        super().__init__()
        self.match_id, self.team, self.hdp = match_id, team, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            if val < 100: raise ValueError
        except: return await interaction.response.send_message("❌ Tiền không hợp lệ!", ephemeral=True)

        user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user or user[0] < val: return await interaction.response.send_message("❌ Không đủ xu!", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, ?, ?, ?, ?, 'PENDING')", 
                 (interaction.user.id, self.match_id, val, self.team, self.hdp))
        await interaction.response.send_message(f"✅ Đã cược **{val:,}** xu cho **{self.team}**", ephemeral=True)

class FootballView(ui.View):
    def __init__(self, match_id, h_name, a_name, hdp, start_time):
        super().__init__(timeout=None)
        self.match_id, self.h_name, self.a_name, self.hdp = match_id, h_name, a_name, hdp
        self.start_time = start_time
        
        # Nhãn nút chỉ chứa Tên đội và Kèo
        self.bet_h.label = f"{h_name} [-{hdp}]"
        self.bet_a.label = f"{a_name} [+{hdp}]"

    @ui.button(style=discord.ButtonStyle.success, custom_id="btn_h")
    async def bet_h(self, interaction: discord.Interaction):
        if datetime.utcnow() > (self.start_time - timedelta(minutes=15)):
            return await interaction.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await interaction.response.send_modal(BetModal(self.match_id, self.h_name, self.hdp))

    @ui.button(style=discord.ButtonStyle.danger, custom_id="btn_a")
    async def bet_a(self, interaction: discord.Interaction):
        if datetime.utcnow() > (self.start_time - timedelta(minutes=15)):
            return await interaction.response.send_message("❌ Đã khóa cược!", ephemeral=True)
        await interaction.response.send_modal(BetModal(self.match_id, self.a_name, -self.hdp))

# ================= HIỂN THỊ TRẬN ĐẤU =================
@tasks.loop(minutes=15)
async def update_matches():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:5]
        await channel.purge(limit=15, check=lambda m: m.author == bot.user)

        for m in matches:
            h_t, a_t = m['homeTeam'], m['awayTeam']
            start_dt = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
            hdp = 0.5 
            score = f"{m['score']['fullTime']['home'] or 0}   -   {m['score']['fullTime']['away'] or 0}"
            
            # Giao diện siêu tối giản: Chỉ có Logo và Tỉ số to ở giữa
            embed = discord.Embed(color=0x37003c)
            embed.set_author(name=f"🏆 {m['competition']['name']}")
            
            # Dùng Field để tạo khoảng trống cho tỉ số to
            embed.add_field(name="\u200b", value=f"## {h_t['name']} \u00A0\u00A0 {score} \u00A0\u00A0 {a_t['name']}", inline=False)
            
            # Hiển thị Logo đội nhà bên trái, đội khách làm ảnh lớn ở dưới để logo rõ nhất
            embed.set_thumbnail(url=h_t.get('crest'))
            embed.set_image(url=a_t.get('crest'))
            
            # Footer chỉ để giờ đá cho gọn
            embed.set_footer(text=f"Bắt đầu: {start_dt.strftime('%H:%M - %d/%m')}")
            
            await channel.send(embed=embed, view=FootballView(m['id'], h_t['name'], a_t['name'], hdp, start_dt))
    except: pass

# ================= KẾT TOÁN & BXH =================
@tasks.loop(minutes=30)
async def settlement():
    pending = query_db("SELECT id, user_id, match_id, amount, team, hdp FROM bets WHERE status = 'PENDING'")
    for b_id, u_id, m_id, amt, team, hdp in pending:
        try:
            r = requests.get(f"https://api.football-data.org/v4/matches/{m_id}", headers={"X-Auth-Token": API_KEY}).json()
            if r.get('status') == 'FINISHED':
                h_s, a_s = r['score']['fullTime']['home'], r['score']['fullTime']['away']
                is_home = (team == r['homeTeam']['name'])
                win = (h_s + hdp > a_s) if is_home else (a_s + hdp > h_s)
                if win: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt * 2, u_id))
                query_db("UPDATE bets SET status = 'DONE' WHERE id = ?", (b_id,))
        except: continue

@tasks.loop(minutes=20)
async def update_lb():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="🏆 ĐẠI GIA XU ẢO", color=0xf1c40f)
    embed.description = "\n".join([f"**#{i+1}** <@{u}>: `{c:,}` xu" for i, (u, c) in enumerate(top)])
    await channel.purge(limit=2); await channel.send(embed=embed)

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    update_matches.start(); update_lb.start(); settlement.start()
    print("🚀 Bot tối giản đã sẵn sàng!")

bot.run(TOKEN)
