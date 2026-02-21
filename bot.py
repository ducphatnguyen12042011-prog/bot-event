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

# ================= CẤU HÌNH HỆ THỐNG =================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_BONG_DA = 1474672512708247582
ID_BXH = 1474674662792232981
ADMIN_ROLES = [1465374336214106237]
COLOR_MAIN = 0x2f3136
COLOR_SUCCESS = 0x2ecc71
COLOR_DANGER = 0xe74c3c

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================= DATABASE ENGINE =================
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ================= UI: TICKET SHOP =================
class TicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🛒 Mở Shop / Hỗ Trợ", style=discord.ButtonStyle.primary, custom_id="shop_ticket", emoji="🎫")
    async def create_ticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        channel = await guild.create_text_channel(f"shop-{interaction.user.name}", overwrites=overwrites)
        
        embed = discord.Embed(title="🛒 SHOP GIAO DỊCH", color=COLOR_MAIN)
        embed.description = f"Chào {interaction.user.mention}, vui lòng nhắn món đồ bạn muốn mua bằng xu ảo tại đây."
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Đã tạo kênh: {channel.mention}", ephemeral=True)

# ================= UI: CÁ ĐỘ BÓNG ĐÁ =================
class BetModal(ui.Modal, title='🎫 NHẬP TIỀN CƯỢC'):
    amount = ui.TextInput(label='Số xu ảo muốn cược (Min 100)', placeholder='Ví dụ: 5000', min_length=1)

    def __init__(self, match_id, team, hdp):
        super().__init__()
        self.match_id, self.team, self.hdp = match_id, team, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            if val < 100: raise ValueError
        except:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

        user = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user or user[0] < val:
            return await interaction.response.send_message("❌ Bạn không đủ xu ảo!", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp) VALUES (?, ?, ?, ?, ?)", 
                 (interaction.user.id, self.match_id, val, self.team, self.hdp))
        
        await interaction.response.send_message(f"✅ Đã cược **{val:,}** xu cho **{self.team}** (Chấp {self.hdp})", ephemeral=True)

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

# ================= CÁC TÁC VỤ TỰ ĐỘNG =================
@tasks.loop(minutes=10)
async def auto_football():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:6]
        await channel.purge(limit=20, check=lambda m: m.author == bot.user)

        for m in matches:
            h_team, a_team = m['homeTeam'], m['awayTeam']
            hdp = random.choice([0, 0.25, 0.5, 0.75, 1.0])
            
            embed = discord.Embed(title=f"🏆 {m['competition']['name']}", color=COLOR_SUCCESS)
            embed.set_thumbnail(url=h_team.get('crest')) # Logo Đội Nhà
            embed.set_image(url=a_team.get('crest'))     # Logo Đội Khách
            embed.set_author(name=f"{h_team['name']} vs {a_team['name']}", icon_url="https://i.imgur.com/vHqB7Y8.png")
            
            embed.description = (
                f"### 🏟️ Tỉ số: `{m['score']['fullTime']['home'] or 0} - {m['score']['fullTime']['away'] or 0}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ **Bắt đầu:** <t:{int(datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ').timestamp())}:F>\n"
                f"⚖️ **Kèo chấp:** Chủ chấp `{hdp}`\n"
                f"💰 **Hình thức:** Cược bằng Coin ảo (1 ăn 1)\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await channel.send(embed=embed, view=FootballView(m['id'], h_team['name'], a_team['name'], hdp))
    except Exception as e: print(f"Lỗi API: {e}")

@tasks.loop(minutes=20)
async def update_lb():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    embed = discord.Embed(title="🏆 BẢNG XẾP HẠNG ĐẠI GIA", color=0xf1c40f, timestamp=datetime.now())
    lb = ""
    for i, (uid, coins) in enumerate(top, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else "👤"
        lb += f"{medal} **Top {i}** | <@{uid}>\n> Tài sản: `{coins:,}` xu\n"
    
    embed.description = lb if lb else "Chưa có dữ liệu."
    await channel.purge(limit=2)
    await channel.send(embed=embed)

# ================= CÁC LỆNH CHÍNH =================
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ TIỀN DISCORD", color=COLOR_MAIN)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.add_field(name="Chủ sở hữu", value=ctx.author.mention, inline=True)
    embed.add_field(name="Số dư hiện có", value=f"`{coins:,}` xu ảo", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def taixiu(ctx, choice: str, amt: int):
    choice = choice.lower()
    if choice not in ['tai', 'xiu']: return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [số tiền]`")
    
    user = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user or user[0] < amt: return await ctx.send("❌ Bạn không đủ xu!")

    msg = await ctx.send(embed=discord.Embed(description="🎰 **Đang lắc bát... hãy chờ nặn!**", color=0xffff00))
    await asyncio.sleep(4)

    d = [random.randint(1, 6) for _ in range(3)]
    total = sum(d)
    res = "tai" if total >= 11 else "xiu"
    win = (choice == res)
    
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt if win else -amt, ctx.author.id))
    
    em = discord.Embed(title=f"🎰 KẾT QUẢ: {total} ({res.upper()})", color=COLOR_SUCCESS if win else COLOR_DANGER)
    em.add_field(name="🎲 Xúc xắc", value=f"**{d[0]} · {d[1]} · {d[2]}**", inline=True)
    em.description = f"### {'✨ THẮNG LỚN!' if win else '💀 THUA RỒI!'}\nBiến động tài sản: `{'+' if win else ''}{amt if win else -amt:,}` xu"
    await msg.edit(embed=em)

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu ảo cho {member.mention}")

@bot.command()
async def setupshop(ctx):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        embed = discord.Embed(title="🛒 SHOP VẬT PHẨM COIN ẢO", color=0x9b59b6)
        embed.description = "Dùng xu ảo bạn kiếm được để mua các phần quà hấp dẫn hoặc Role xịn!"
        await ctx.send(embed=embed, view=TicketView())

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL)')
    auto_football.start()
    update_lb.start()
    bot.add_view(TicketView())
    print(f"🔥 Bot {bot.user} đã lên đèn!")

bot.run(TOKEN)
