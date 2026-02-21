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

# Tải biến môi trường
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')

# Cấu hình ID
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ADMIN_ROLES = [1465374336214106237] # Thay bằng ID Role Admin của bạn

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ================= DATABASE ENGINE =================
def query_db(sql, params=(), one=False):
    # Railway xóa file khi restart, nhưng chúng ta dùng SQLite cho đơn giản 
    # Nếu muốn lưu lâu dài hãy dùng Railway PostgreSQL
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ================= UI COMPONENTS (GIAO DIỆN) =================
class BetModal(ui.Modal, title='🎫 ĐẶT CƯỢC TRẬN ĐẤU'):
    amount = ui.TextInput(label='Số xu muốn cược (Min 100)', placeholder='Ví dụ: 500', min_length=1)

    def __init__(self, match_id, team_name):
        super().__init__()
        self.match_id = match_id
        self.team_name = team_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            if val < 100: raise ValueError
        except:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ (Tối thiểu 100)!", ephemeral=True)

        user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user_data or user_data[0] < val:
            return await interaction.response.send_message("❌ Bạn không đủ xu! Hãy chơi Tài Xỉu hoặc xin Admin.", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team) VALUES (?, ?, ?, ?)", 
                 (interaction.user.id, self.match_id, val, self.team_name))
        
        await interaction.response.send_message(f"✅ Đã cược **{val:,}** xu cho **{self.team_name}**!", ephemeral=True)

class FootballView(ui.View):
    def __init__(self, match_id, home_name, away_name):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.home_name = home_name
        self.away_name = away_name

    @ui.button(label="Cược Đội Nhà", style=discord.ButtonStyle.success, emoji="🏟️")
    async def bet_home(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BetModal(self.match_id, self.home_name))

    @ui.button(label="Cược Đội Khách", style=discord.ButtonStyle.danger, emoji="✈️")
    async def bet_away(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BetModal(self.match_id, self.away_name))

# ================= AUTOMATIC TASKS =================
@tasks.loop(minutes=15)
async def update_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    try:
        headers = {"X-Auth-Token": API_KEY}
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])[:5] 

        # Xóa tin nhắn bot cũ để tránh rác kênh
        await channel.purge(limit=10, check=lambda m: m.author == bot.user)

        for m in matches:
            h_team, a_team = m['homeTeam'], m['awayTeam']
            embed = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x2f3136)
            embed.set_author(name="TRẬN ĐẤU THỰC TẾ (KÈO CHẤP 0.5 - TỈ LỆ 1:1)")
            embed.set_thumbnail(url=h_team.get('crest')) # Logo Đội Nhà
            embed.set_image(url=a_team.get('crest'))     # Logo Đội Khách (Hiển thị lớn bên dưới)
            
            embed.description = (
                f"### 🏟️ {h_team['name']} vs {a_team['name']}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ **Bắt đầu:** <t:{int(datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ').timestamp())}:R>\n"
                f"💰 **Hình thức:** Thắng ăn cả, Thua mất hết\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await channel.send(embed=embed, view=FootballView(m['id'], h_team['name'], a_team['name']))
    except Exception as e: print(f"Lỗi API: {e}")

@tasks.loop(minutes=30)
async def update_lb():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    top_users = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    embed = discord.Embed(title="🏆 BẢNG VINH DANH ĐẠI GIA", color=0xf1c40f, timestamp=datetime.now())
    lb_text = ""
    for i, (uid, coins) in enumerate(top_users, 1):
        lb_text += f"**#{i}** | <@{uid}>: `{coins:,}` xu\n"
    
    embed.description = lb_text if lb_text else "Chưa có dữ liệu."
    await channel.purge(limit=1)
    await channel.send(embed=embed)

# ================= COMMANDS =================
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ TIỀN DISCORD", color=0x3498db)
    embed.add_field(name="Chủ sở hữu", value=ctx.author.mention)
    embed.add_field(name="Số dư", value=f"`{coins:,}` xu")
    await ctx.send(embed=embed)

@bot.command()
async def taixiu(ctx, choice: str, amt: int):
    choice = choice.lower()
    if choice not in ['tai', 'xiu'] or amt < 10: 
        return await ctx.send("Cú pháp: `!taixiu [tai/xiu] [số tiền]`")
    
    user_coins = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_coins or user_coins[0] < amt:
        return await ctx.send("❌ Bạn không đủ xu!")

    dices = [random.randint(1, 6) for _ in range(3)]
    total = sum(dices)
    res = "tai" if total >= 11 else "xiu"
    win = (choice == res)
    
    reward = amt if win else -amt
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, ctx.author.id))
    
    embed = discord.Embed(title="🎰 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if win else 0xe74c3c)
    embed.description = f"🎲 Xúc xắc: **{dices[0]} - {dices[1]} - {dices[2]}** (Tổng: **{total}**)\n"
    embed.description += f"🎯 Kết quả: **{res.upper()}**\n\n"
    embed.description += f"**{'✨ THẮNG' if win else '💀 THUA'}**: `{reward:,}` xu"
    await ctx.send(embed=embed)

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(role.id in ADMIN_ROLES for role in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu cho {member.mention}")

# ================= STARTUP =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT)')
    update_football.start()
    update_lb.start()
    print(f"🔥 Bot {bot.user} đang chạy trên Railway!")

bot.run(TOKEN)
