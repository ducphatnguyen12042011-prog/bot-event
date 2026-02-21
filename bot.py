import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime, timedelta

# ======================== CẤU HÌNH HỆ THỐNG ========================
TOKEN = "YOUR_DISCORD_TOKEN"
API_KEY = "YOUR_FOOTBALL_API_KEY"

# ID CÁC KÊNH (Dựa trên thông tin bạn cung cấp)
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ID_KENH_SHOP = 1474695449167400972
ID_CATEGORY_TICKET = 1474672512708247582 # Danh mục tạo kênh hỗ trợ

# ID ROLE ADMIN
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]

# CẤU HÌNH KHÁC
BIG_LEAGUES = ['PL', 'CL', 'BL1', 'SA', 'PD', 'FL1', 'WC']
DB_PATH = 'economy.db'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ======================== HỆ THỐNG DATABASE ========================
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

def init_db():
    query_db('''CREATE TABLE IF NOT EXISTS users 
                (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)''')
    query_db('''CREATE TABLE IF NOT EXISTS bets 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                 match_id TEXT, amount INTEGER, team TEXT, hdp REAL)''')
    print("✅ Database đã sẵn sàng hoạt động!")

# ======================== HỆ THỐNG SHOP: 1 CHẠM TỰ ĐỘNG ========================
class ShopView(ui.View):
    def __init__(self, item_name, price):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.price = price

    @ui.button(label="🛒 MUA NGAY", style=discord.ButtonStyle.success, custom_id="auto_buy", emoji="💰")
    async def buy_callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # 1. Kiểm tra số dư
        user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (user_id,), one=True)
        balance = user_data[0] if user_data else 0

        if balance < self.price:
            return await interaction.response.send_message(
                f"❌ **Giao dịch thất bại!**\nBạn cần `{self.price:,}` xu nhưng chỉ có `{balance:,}` xu.", 
                ephemeral=True
            )

        # 2. Thực hiện trừ tiền
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (self.price, user_id))
        
        # 3. Tạo Ticket hỗ trợ tự động
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        for r_id in ADMIN_ROLES:
            role = guild.get_role(r_id)
            if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ticket_chan = await guild.create_text_channel(
            name=f"📦-{interaction.user.name}", 
            overwrites=overwrites, 
            category=guild.get_channel(ID_CATEGORY_TICKET)
        )
        
        # 4. Gửi hóa đơn vào Ticket
        embed_invoice = discord.Embed(title="📜 HÓA ĐƠN MUA HÀNG", color=0x2ecc71, timestamp=datetime.now())
        embed_invoice.add_field(name="👤 Khách hàng", value=interaction.user.mention, inline=True)
        embed_invoice.add_field(name="📦 Sản phẩm", value=f"**{self.item_name}**", inline=True)
        embed_invoice.add_field(name="💰 Trạng thái", value=f"Đã thanh toán `{self.price:,}` xu", inline=False)
        embed_invoice.set_footer(text="Vui lòng chờ Admin bàn giao vật phẩm!")
        
        await ticket_chan.send(content=f"🔔 <@&{ADMIN_ROLES[0]}> | Có đơn hàng mới cần xử lý!", embed=embed_invoice)
        
        # 5. Phản hồi cho khách
        await interaction.response.send_message(
            f"✅ **Thanh toán thành công!**\nĐã trừ `{self.price:,}` xu. Kênh hỗ trợ của bạn: {ticket_chan.mention}", 
            ephemeral=True
        )

# ======================== LỆNH QUẢN TRỊ & VÍ TIỀN ========================
@bot.command()
async def dangban(ctx, price: int, *, name: str):
    """Lệnh dành cho Admin để đăng sản phẩm lên Shop"""
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    if ctx.channel.id != ID_KENH_SHOP:
        return await ctx.send(f"❌ Bạn phải dùng lệnh này tại kênh <#{ID_KENH_SHOP}>")
    
    eb = discord.Embed(title="🛍️ CỬA HÀNG TỰ ĐỘNG", color=0x9b59b6)
    eb.set_thumbnail(url="https://i.imgur.com/39S5uG7.png")
    eb.description = f"### {name}\n━━━━━━━━━━━━━━━━━━━━\n💵 Giá bán: **{price:,} xu**\n\n*Nhấn nút dưới để mua và tạo Ticket giao hàng.*"
    
    await ctx.send(embed=eb, view=ShopView(name, price))
    await ctx.message.delete()

@bot.command()
async def vi(ctx):
    """Kiểm tra số dư ví cá nhân"""
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    eb = discord.Embed(title="💳 VÍ TIỀN DISCORD", description=f"Số dư: **{coins:,}** xu", color=0xf1c40f)
    eb.set_author(name=ctx.author.name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=eb)

@bot.command()
async def nap(ctx, m: discord.Member, amt: int):
    """Admin nạp xu cho thành viên"""
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (m.id,))
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, m.id))
    await ctx.send(f"✅ Đã nạp thành công **{amt:,}** xu cho {m.mention}")

# ======================== ⚽ BÓNG ĐÁ: LIVE SCORE & KÈO CHẤP ========================
class BetModal(ui.Modal, title='🎫 ĐẶT CƯỢC'):
    bet_input = ui.TextInput(label='Số xu muốn cược (Tối thiểu 100)', placeholder='Nhập số tiền...')
    def __init__(self, mid, team, hdp):
        super().__init__()
        self.mid, self.team, self.hdp = mid, team, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.bet_input.value)
            if val < 100: raise ValueError
        except: return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)
        
        d = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not d or d[0] < val: return await interaction.response.send_message("❌ Ví bạn không đủ xu!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp) VALUES (?, ?, ?, ?, ?)", 
                 (interaction.user.id, self.mid, val, self.team, self.hdp))
        await interaction.response.send_message(f"✅ Đã cược **{val:,}** xu cho **{self.team}**!", ephemeral=True)

@tasks.loop(minutes=5)
async def auto_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        req = requests.get("https://api.football-data.org/v4/matches", headers=headers)
        if req.status_code != 200: return
        
        matches = req.json().get('matches', [])[:10]
        old_pins = await channel.pins()

        # Dọn kênh tránh spam
        await channel.purge(limit=20, check=lambda m: m.author == bot.user and not m.pinned)

        for m in matches:
            status = m['status']
            h_team, a_team = m['homeTeam'], m['awayTeam']
            h_score = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
            a_score = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0
            
            # TRẬN SẮP DIỄN RA (LOGO CÂN BẰNG 1:1)
            if status in ['SCHEDULED', 'TIMED']:
                hdp = random.choice([0, 0.5, 1.0, 1.5])
                time_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
                
                eb = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x3498db)
                eb.set_author(name=h_team['name'], icon_url=h_team.get('crest'))
                eb.set_thumbnail(url=a_team.get('crest'))
                eb.description = f"### {h_team['name']}  vs  {a_team['name']}\n━━━━━━━━━━━━\n⏰ Giờ đá: `{time_vn}`\n⚖️ Kèo: Chủ chấp `{hdp}`"
                
                v = ui.View(timeout=None)
                b1 = ui.Button(label=f"Cược {h_team['name']}", style=discord.ButtonStyle.success)
                b2 = ui.Button(label=f"Cược {a_team['name']}", style=discord.ButtonStyle.danger)
                
                b1.callback = lambda i, t=h_team['name'], mid=m['id'], h=hdp: i.response.send_modal(BetModal(mid, t, h))
                b2.callback = lambda i, t=a_team['name'], mid=m['id'], h=hdp: i.response.send_modal(BetModal(mid, t, -h))
                
                v.add_item(b1); v.add_item(b2)
                msg = await channel.send(embed=eb, view=v)
                if m['competition']['code'] in BIG_LEAGUES: await msg.pin()

            # TRẬN ĐANG LIVE
            elif status in ['IN_PLAY', 'PAUSED']:
                eb = discord.Embed(title=f"🔴 LIVE SCORE: {m['competition']['name']}", color=0xff0000)
                eb.set_author(name=h_team['name'], icon_url=h_team.get('crest'))
                eb.set_thumbnail(url=a_team.get('crest'))
                eb.description = f"# {h_score}  —  {a_score}\n━━━━━━━━━━━━\n⚽ Trận đấu đang diễn ra..."
                await channel.send(embed=eb)

            # KẾT THÚC -> TỰ ĐỘNG GỠ GHIM
            elif status == 'FINISHED':
                for pin in old_pins:
                    if pin.author == bot.user and h_team['name'] in pin.embeds[0].author.name:
                        await pin.unpin()
                        
    except Exception as e: print(f"Lỗi API Bóng Đá: {e}")

# ======================== 🎲 TÀI XỈU NẶN & BXH ========================
@bot.command()
async def taixiu(ctx, choice: str, amt: int):
    choice = choice.lower()
    if choice not in ['tai', 'xiu']: return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [tiền]`")
    
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not d or d[0] < amt: return await ctx.send("❌ Bạn không đủ tiền cược!")

    msg = await ctx.send(embed=discord.Embed(description="🎲 **Đang lắc bát... nặn nào!**", color=0xffff00))
    await asyncio.sleep(3)

    dice = [random.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    res = "tai" if total >= 11 else "xiu"
    win = (choice == res)
    
    change = int(amt * 0.95) if win else -amt
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (change, ctx.author.id))
    
    eb = discord.Embed(title="🎰 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if win else 0xe74c3c)
    eb.description = f"🎲 **{dice[0]} · {dice[1]} · {dice[2]}** = **{total}** ({res.upper()})\n\n### {'✅ THẮNG' if win else '❌ THUA'}: `{change:,}` xu"
    await msg.edit(embed=eb)

@tasks.loop(minutes=10)
async def update_leaderboard():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    eb = discord.Embed(title="🏆 BẢNG VINH DANH ĐẠI GIA", color=0xffd700, timestamp=datetime.now())
    lb_text = ""
    for i, (uid, coins) in enumerate(top, 1):
        medal = ["🥇", "🥈", "🥉", "👤"][i-1] if i <= 3 else "👤"
        lb_text += f"{medal} **Top {i}** | <@{uid}>: `{coins:,}` xu\n"
    
    eb.description = lb_text or "Chưa có dữ liệu người chơi."
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=eb)

# ======================== KHỞI CHẠY BOT ========================
@bot.event
async def on_ready():
    init_db()
    auto_football.start()
    update_leaderboard.start()
    print(f"🚀 {bot.user} đã online và sẵn sàng phục vụ!")
