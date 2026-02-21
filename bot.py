import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import requests
import asyncio
from datetime import datetime, timedelta

# ==========================================================
# ⚙️ CẤU HÌNH HỆ THỐNG
# ==========================================================
TOKEN = "YOUR_BOT_TOKEN"
API_KEY = "YOUR_FOOTBALL_API_KEY"

ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ID_KENH_SHOP = 1474695449167400972
ID_CATEGORY_TICKET = 1474672512708247582 

ADMIN_ROLES = [1465374336214106237, 1465376049452810306]
DB_PATH = 'economy_pro.db'

intents = discord.Intents.all() 
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ==========================================================
# 🗄️ DATABASE
# ==========================================================
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ==========================================================
# ⚽ HỆ THỐNG BẢNG ĐẤU (GIAO DIỆN 1:1)
# ==========================================================
async def update_football_board():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel: return

    headers = {"X-Auth-Token": API_KEY}
    try:
        # Lấy các trận đấu trong 24h tới
        r = requests.get("https://api.football-data.org/v4/matches", headers=headers, timeout=10)
        if r.status_code != 200:
            print(f"❌ Lỗi API: {r.status_code}")
            return

        data = r.json()
        matches = data.get('matches', [])[:10]

        # Xóa tin cũ (giữ lại tin nhắn ghim)
        await channel.purge(limit=30, check=lambda m: m.author == bot.user and not m.pinned)

        if not matches:
            await channel.send(" hiện tại chưa có trận đấu mới cập nhật.")
            return

        for m in matches:
            home = m['homeTeam']
            away = m['awayTeam']
            status = m['status']
            
            # FORMAT GIỜ VN
            utc_time = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ")
            vn_time = (utc_time + timedelta(hours=7)).strftime("%H:%M - %d/%m")

            # THIẾT KẾ EMBED ĐỐI XỨNG 1:1
            # Logo Home đặt ở Author Icon, Logo Away đặt ở Thumbnail
            embed = discord.Embed(
                title=f"🏆 {m['competition']['name']}",
                description=f"**{home['name']}** VS  **{away['name']}**",
                color=0x00ff00 if status == 'IN_PLAY' else 0x3498db
            )
            
            # Cấu hình logo đối xứng
            embed.set_author(name=f"CHỦ NHÀ: {home['name']}", icon_url=home.get('crest'))
            embed.set_thumbnail(url=away.get('crest'))
            
            if status in ['IN_PLAY', 'PAUSED']:
                h_s = m['score']['fullTime']['home'] or 0
                a_s = m['score']['fullTime']['away'] or 0
                embed.add_field(name="🔴 TRẠNG THÁI: LIVE", value=f"## TỈ SỐ: {h_s} - {a_s}", inline=False)
            else:
                embed.add_field(name="⏰ THỜI GIAN", value=f"`{vn_time}`", inline=True)
                embed.add_field(name="⚖️ KÈO CHẤP", value="`Chủ chấp 0.5`", inline=True)

            embed.set_footer(text=f"ID Trận: {m['id']} | Đội khách logo bên phải ➡️")

            # NÚT BẤM CƯỢC
            view = ui.View(timeout=None)
            view.add_item(ui.Button(label=f"Cược {home['shortName'] or home['name']}", style=discord.ButtonStyle.success, custom_id=f"bet_h_{m['id']}"))
            view.add_item(ui.Button(label=f"Cược {away['shortName'] or away['name']}", style=discord.ButtonStyle.danger, custom_id=f"bet_a_{m['id']}"))
            
            await channel.send(embed=embed, view=view)

    except Exception as e:
        print(f"❌ Lỗi xử lý bảng đấu: {e}")

# ==========================================================
# 🛒 SHOP 1 CHẠM & TICKET
# ==========================================================
class ShopView(ui.View):
    def __init__(self, item, price):
        super().__init__(timeout=None)
        self.item, self.price = item, price

    @ui.button(label="🛒 THANH TOÁN NGAY", style=discord.ButtonStyle.primary, custom_id="buy")
    async def buy(self, interaction: discord.Interaction):
        res = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        balance = res[0] if res else 0
        
        if balance < self.price:
            return await interaction.response.send_message("❌ Bạn không đủ xu!", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (self.price, interaction.user.id))
        
        # TẠO TICKET
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        chan = await guild.create_text_channel(name=f"bill-{interaction.user.name}", overwrites=overwrites, category=guild.get_channel(ID_CATEGORY_TICKET))
        
        await chan.send(f"✅ Giao dịch thành công!\nKhách: {interaction.user.mention}\nMua: **{self.item}**\nGiá: `{self.price:,}` xu.\nAdmin <@&{ADMIN_ROLES[0]}> vào kiểm tra nhé!")
        await interaction.response.send_message(f"✅ Đã mua! Xem tại: {chan.mention}", ephemeral=True)

# ==========================================================
# 🛠️ LỆNH ĐIỀU KHIỂN
# ==========================================================
@bot.command()
async def update(ctx):
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    await ctx.send("🔄 Đang làm mới bảng đấu...")
    await update_football_board()

@bot.command()
async def vi(ctx):
    query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (ctx.author.id,))
    res = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(f"💳 Ví của {ctx.author.mention}: **{res[0]:,}** xu.")

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
    await ctx.send(f"✅ Đã nạp `{amount:,}` xu cho {member.mention}")

@bot.command()
async def dangban(ctx, price: int, *, name: str):
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    eb = discord.Embed(title="🛍️ CỬA HÀNG", description=f"Sản phẩm: **{name}**\nGiá: `{price:,}` xu", color=0x9b59b6)
    await ctx.send(embed=eb, view=ShopView(name, price))

# ==========================================================
# 🚀 KHỞI CHẠY
# ==========================================================
@tasks.loop(minutes=10)
async def auto_refresh():
    await update_football_board()

@bot.event
async def on_ready():
    query_db('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)''')
    auto_refresh.start()
    print(f"✅ Bot {bot.user} đã sẵn sàng!")

bot.run(TOKEN)
