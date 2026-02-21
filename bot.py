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

intents = discord.Intents.default()
intents.message_content = True
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
    amount = ui.TextInput(label='Nhập số xu ảo', placeholder='Tối thiểu 100...', min_length=1)

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
        await interaction.response.send_message(f"✅ Đã cược **{val:,}** xu cho **{self.team}**", ephemeral=True)

class FootballView(ui.View):
    def __init__(self, match_id, h_name, a_name, hdp, start_time):
        # timeout=None để nút không bao giờ bị lỗi "Tương tác thất bại"
        super().__init__(timeout=None)
        self.match_id = match_id
        self.h_name, self.a_name = h_name, a_name
        self.hdp = hdp
        self.start_time = start_time
        
        # Nhãn nút ghi rõ kèo chấp
        self.bet_h.label = f"{h_name} [-{hdp}]"
        self.bet_a.label = f"{a_name} [+{hdp}]"
        
        # Gán custom_id duy nhất để fix lỗi tương tác
        self.bet_h.custom_id = f"home_{match_id}"
        self.bet_a.custom_id = f"away_{match_id}"

    @ui.button(style=discord.ButtonStyle.success)
    async def bet_h(self, interaction: discord.Interaction):
        if datetime.utcnow() > (self.start_time - timedelta(minutes=15)):
            return await interaction.response.send_message("❌ Đã hết thời gian đặt cược!", ephemeral=True)
        await interaction.response.send_modal(BetModal(self.match_id, self.h_name, self.hdp))

    @ui.button(style=discord.ButtonStyle.danger)
    async def bet_a(self, interaction: discord.Interaction):
        if datetime.utcnow() > (self.start_time - timedelta(minutes=15)):
            return await interaction.response.send_message("❌ Đã hết thời gian đặt cược!", ephemeral=True)
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
            score = f"{m['score']['fullTime']['home'] or 0}  -  {m['score']['fullTime']['away'] or 0}"
            
            # Giao diện ổn định nhất (Premier League Style)
            embed = discord.Embed(title=f"⚽ {score}", color=0x37003c)
            embed.set_author(name=f"{h_t['name']}", icon_url=h_t.get('crest'))
            embed.set_thumbnail(url=a_t.get('crest'))
            
            # Thông tin thời gian và kèo cách dòng rõ ràng
            embed.description = (
                f"**{h_t['name']} VS {a_t['name']}**\n"
                f"\u200b\n"
                f"⏰ **Bắt đầu:** <t:{int(start_dt.timestamp())}:F>\n"
                f"⚖️ **Kèo chấp:** `{h_t['name']} chấp {hdp}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            
            await channel.send(embed=embed, view=FootballView(m['id'], h_t['name'], a_t['name'], hdp, start_dt))
    except Exception as e:
        print(f"Lỗi fetch data: {e}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    update_matches.start()
    print("🚀 Bot đã sẵn sàng và fix toàn bộ lỗi tương tác!")

bot.run(TOKEN)
