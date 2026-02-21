import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime, timedelta

# --- CẤU HÌNH HỆ THỐNG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]
DB_PATH = 'economy.db'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- KẾT NỐI DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# --- MODAL ĐẶT CƯỢC ---
class BettingModal(ui.Modal, title='🎫 NHẬP SỐ TIỀN CƯỢC'):
    amount = ui.TextInput(label='Số xu muốn cược', placeholder='Tối thiểu 100...', min_length=1)

    def __init__(self, m_id, team, choice, hdp):
        super().__init__()
        self.m_id, self.team, self.choice, self.hdp = m_id, team, choice, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value.strip())
            if amt < 100: raise ValueError
        except: return await interaction.response.send_message("❌ Tiền không hợp lệ!", ephemeral=True)

        bal = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not bal or bal[0] < amt: return await interaction.response.send_message("❌ Bạn không đủ xu!", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, interaction.user.id))
        query_db("INSERT INTO bets (match_id, user_id, amount, choice, hdp) VALUES (?, ?, ?, ?, ?)", 
                 (self.m_id, interaction.user.id, amt, self.choice, self.hdp))
        await interaction.response.send_message(f"✅ Đã đặt **{amt:,}** xu cho **{self.team}**", ephemeral=True)

# --- ⚽ BÓNG ĐÁ: LOGO 1:1 & KÈO CHẤP ---
@tasks.loop(minutes=10)
async def auto_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=SCHEDULED", headers=headers).json()
        matches = res.get('matches', [])[:5]
        await channel.purge(limit=20, check=lambda m: m.author == bot.user)

        for m in matches:
            h_team, a_team = m['homeTeam'], m['awayTeam']
            hdp = random.choice([0, 0.5, 1.0, 1.5])
            time_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
            
            # Embed cân bằng Logo
            embed = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x3498db)
            embed.set_author(name=f"Đội Nhà: {h_team['name']}", icon_url=h_team.get('crest'))
            embed.set_thumbnail(url=a_team.get('crest')) # Đội khách ở Thumbnail
            
            embed.description = (
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏟️ **{h_team['name']}** vs **{a_team['name']}**\n"
                f"⏰ Giờ đá: `{time_vn}`\n"
                f"⚖️ Kèo chấp: `{hdp}` (Đội nhà chấp)\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

            view = ui.View(timeout=None)
            view.add_item(ui.Button(label=f"{h_team['name']} (-{hdp})", style=discord.ButtonStyle.success, custom_id=f"h_{m['id']}"))
            view.add_item(ui.Button(label=f"{a_team['name']} (+{hdp})", style=discord.ButtonStyle.danger, custom_id=f"a_{m['id']}"))
            
            # Xử lý sự kiện nút bấm (giản lược cho gọn mã)
            async def btn_call(interaction):
                cid = interaction.data['custom_id']
                team = h_team['name'] if cid.startswith('h_') else a_team['name']
                choice = 0 if cid.startswith('h_') else 1
                await interaction.response.send_modal(BettingModal(m['id'], team, choice, hdp))
            
            for item in view.children: item.callback = btn_call
            
            await channel.send(embed=embed, view=view)
    except: pass

# --- 🎲 TÀI XỈU "NẶN" KỊCH TÍNH ---
@bot.command()
async def taixiu(ctx, choice: str, amt_str: str):
    choice = choice.lower()
    if choice not in ['tai', 'xiu']: return
    try: amt = int(amt_str)
    except: return await ctx.send("❌ Nhập số tiền cược!")

    bal = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not bal or bal[0] < amt: return await ctx.send("❌ Hết tiền rồi!")

    msg = await ctx.send(embed=discord.Embed(title="🎲 ĐANG LẮC XÚC XẮC...", color=0xffff00))
    await asyncio.sleep(3) # Hiệu ứng nặn

    dices = [random.randint(1, 6) for _ in range(3)]
    total = sum(dices)
    res = "tai" if total >= 11 else "xiu"
    win = (choice == res)
    
    if win: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(amt * 0.95), ctx.author.id))
    else: query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, ctx.author.id))

    embed = discord.Embed(title="🎰 KẾT QUẢ", color=0x2ecc71 if win else 0xe74c3c)
    embed.description = f"🎲 **{dices}** -> **{total}** ({res.upper()})\n{'✅ Bạn thắng!' if win else '❌ Bạn thua!'}"
    await msg.edit(embed=embed)

# --- 🛒 SHOP TICKET MẪU CHUẨN ---
@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🛒 HỆ THỐNG CỬA HÀNG & TICKET", color=0x9b59b6)
    embed.description = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ **Sản phẩm đang bán:**\n"
        "• 💎 Gói Robux: 50,000 xu\n"
        "• ⚔️ Cày thuê Blox Fruit: 100,000 xu\n"
        "• 👑 VIP Role: 500,000 xu\n\n"
        "📌 *Dùng lệnh `!mua [tên]` để mở Ticket tự động!*"
        "\n━━━━━━━━━━━━━━━━━━━━"
    )
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, user_id INTEGER, amount INTEGER, choice INTEGER, hdp REAL, status INTEGER DEFAULT 0)')
    auto_football.start()
    print(f"🚀 {bot.user} ĐÃ SẴN SÀNG!")

bot.run(TOKEN)
