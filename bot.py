import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
import asyncio
import logging
from datetime import datetime, timedelta

# ==========================================================
# ⚙️ CẤU HÌNH HỆ THỐNG (THAY ĐỔI TẠI ĐÂY)
# ==========================================================
TOKEN = "YOUR_BOT_TOKEN"
API_KEY = "YOUR_FOOTBALL_API_KEY"

# ID CÁC KÊNH VÀ DANH MỤC
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ID_KENH_SHOP = 1474695449167400972
ID_CATEGORY_TICKET = 1474672512708247582 

# ID ROLE QUẢN TRỊ
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]

# CẤU HÌNH KỸ THUẬT
DB_PATH = 'economy_v2.db'
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ==========================================================
# 🗄️ HỆ THỐNG DATABASE (SQLITE)
# ==========================================================
class Database:
    @staticmethod
    def execute(sql, params=()):
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            return cur

    @staticmethod
    def fetch(sql, params=(), one=False):
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            res = cur.fetchall()
            return (res[0] if res else None) if one else res

def init_db():
    # Bảng người dùng
    Database.execute('''CREATE TABLE IF NOT EXISTS users 
                       (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)''')
    # Bảng lưu lịch sử cược bóng đá
    Database.execute('''CREATE TABLE IF NOT EXISTS bets 
                       (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                        match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT DEFAULT 'OPEN')''')
    # Bảng lưu sản phẩm trong Shop
    Database.execute('''CREATE TABLE IF NOT EXISTS shop_items 
                       (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price INTEGER)''')
    logging.info("Hệ thống Database đã được khởi tạo.")

# ==========================================================
# 🛒 HỆ THỐNG SHOP 1 NÚT BẤM (ONE-CLICK TICKET)
# ==========================================================
class PersistentShopView(ui.View):
    """View này giúp nút bấm tồn tại mãi mãi ngay cả khi bot khởi động lại"""
    def __init__(self, item_name, price):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.price = price

    @ui.button(label="🛒 MUA NGAY", style=discord.ButtonStyle.success, custom_id="buy_button_persistent", emoji="💰")
    async def buy_button(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # Kiểm tra tiền
        user_data = Database.fetch("SELECT coins FROM users WHERE user_id = ?", (user_id,), one=True)
        balance = user_data[0] if user_data else 0

        if balance < self.price:
            embed_err = discord.Embed(description=f"❌ **Không đủ tiền!** Bạn cần `{self.price:,}` xu.", color=0xe74c3c)
            return await interaction.response.send_message(embed=embed_err, ephemeral=True)

        # Trừ tiền ngay lập tức
        Database.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (self.price, user_id))
        
        # Tạo Ticket
        guild = interaction.guild
        category = guild.get_channel(ID_CATEGORY_TICKET)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        for role_id in ADMIN_ROLES:
            admin_role = guild.get_role(role_id)
            if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(
            name=f"📦-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        # Gửi thông báo xác nhận
        embed_success = discord.Embed(title="✅ THANH TOÁN THÀNH CÔNG", color=0x2ecc71, timestamp=datetime.now())
        embed_success.add_field(name="📦 Sản phẩm", value=self.item_name, inline=True)
        embed_success.add_field(name="💰 Đã trừ", value=f"{self.price:,} xu", inline=True)
        embed_success.set_footer(text="Admin sẽ sớm phản hồi bạn trong kênh này.")
        
        await ticket_channel.send(content=f"🔔 <@&{ADMIN_ROLES[0]}> | Đơn hàng mới từ {interaction.user.mention}", embed=embed_success)
        await interaction.response.send_message(f"✅ Đã trừ tiền! Hãy kiểm tra kênh: {ticket_channel.mention}", ephemeral=True)

# ==========================================================
# ⚽ HỆ THỐNG BÓNG ĐÁ (LIVE SCORE & BETTING)
# ==========================================================
class BetModal(ui.Modal, title='🎫 XÁC NHẬN ĐẶT CƯỢC'):
    amount_input = ui.TextInput(label='Số tiền cược (Min: 100)', placeholder='Nhập số xu...', min_length=1)

    def __init__(self, match_id, team_name, handicap):
        super().__init__()
        self.match_id = match_id
        self.team_name = team_name
        self.handicap = handicap

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet_amt = int(self.amount_input.value)
            if bet_amt < 100:
                return await interaction.response.send_message("❌ Tiền cược tối thiểu là 100 xu!", ephemeral=True)
        except ValueError:
            return await interaction.response.send_message("❌ Vui lòng nhập một con số hợp lệ!", ephemeral=True)

        user_data = Database.fetch("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user_data or user_data[0] < bet_amt:
            return await interaction.response.send_message("❌ Ví của bạn không đủ số dư!", ephemeral=True)

        # Trừ tiền và lưu cược
        Database.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (bet_amt, interaction.user.id))
        Database.execute("INSERT INTO bets (user_id, match_id, amount, team, hdp) VALUES (?, ?, ?, ?, ?)",
                         (interaction.user.id, self.match_id, bet_amt, self.team_name, self.handicap))
        
        await interaction.response.send_message(f"✅ Đã cược `{bet_amt:,}` xu cho **{self.team_name}**!", ephemeral=True)

@tasks.loop(minutes=5)
async def football_update_task():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return

    headers = {"X-Auth-Token": API_KEY}
    try:
        response = requests.get("https://api.football-data.org/v4/matches", headers=headers, timeout=10)
        if response.status_code != 200: return

        data = response.json()
        matches = data.get('matches', [])[:10]
        pinned_messages = await channel.pins()

        # Dọn dẹp tin nhắn bot không ghim
        await channel.purge(limit=20, check=lambda m: m.author == bot.user and not m.pinned)

        for match in matches:
            home = match['homeTeam']
            away = match['awayTeam']
            status = match['status']
            h_score = match['score']['fullTime']['home'] or 0
            a_score = match['score']['fullTime']['away'] or 0

            # 🟡 TRẠNG THÁI: CHUẨN BỊ (SẮP ĐÁ)
            if status in ['SCHEDULED', 'TIMED']:
                hdp = random.choice([0, 0.5, 1.0, 1.5])
                utc_time = datetime.strptime(match['utcDate'], "%Y-%m-%dT%H:%M:%SZ")
                vn_time = (utc_time + timedelta(hours=7)).strftime("%H:%M %d/%m")

                embed = discord.Embed(title=f"🏆 {match['competition']['name']}", color=0x3498db)
                embed.set_author(name=home['name'], icon_url=home.get('crest'))
                embed.set_thumbnail(url=away.get('crest'))
                embed.description = (
                    f"### {home['name']} VS {away['name']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏰ **Giờ đá:** `{vn_time}`\n"
                    f"⚖️ **Kèo chấp:** Chủ chấp `{hdp}`\n"
                    f"💰 **Tỉ lệ:** 1 : 1"
                )
                
                view = ui.View(timeout=None)
                btn_home = ui.Button(label=f"Cược {home['name']}", style=discord.ButtonStyle.success)
                btn_away = ui.Button(label=f"Cược {away['name']}", style=discord.ButtonStyle.danger)

                btn_home.callback = lambda i, m_id=match['id'], t=home['name'], h=hdp: i.response.send_modal(BetModal(m_id, t, h))
                btn_away.callback = lambda i, m_id=match['id'], t=away['name'], h=hdp: i.response.send_modal(BetModal(m_id, t, -h))
                
                view.add_item(btn_home); view.add_item(btn_away)
                msg = await channel.send(embed=embed, view=view)
                
                # Ghim trận nếu cần
                if match['competition']['code'] in ['PL', 'CL', 'BL1']: await msg.pin()

            # 🔴 TRẠNG THÁI: ĐANG ĐÁ (LIVE)
            elif status in ['IN_PLAY', 'PAUSED']:
                embed_live = discord.Embed(title=f"🔴 LIVE: {match['competition']['name']}", color=0xff0000)
                embed_live.description = f"## {home['name']}  {h_score} — {a_score}  {away['name']}\n> *Tỉ số cập nhật trực tiếp*"
                embed_live.set_author(name=home['name'], icon_url=home.get('crest'))
                embed_live.set_thumbnail(url=away.get('crest'))
                await channel.send(embed=embed_live)

            # 🏁 TRẠNG THÁI: KẾT THÚC (TỰ GỠ GHIM)
            elif status == 'FINISHED':
                for pin in pinned_messages:
                    if pin.author == bot.user and home['name'] in (pin.embeds[0].author.name if pin.embeds else ""):
                        await pin.unpin()

    except Exception as e:
        logging.error(f"Lỗi cập nhật bóng đá: {e}")

# ==========================================================
# 🎰 TRÒ CHƠI TÀI XỈU (NẶN BÁT)
# ==========================================================
@bot.command()
async def taixiu(ctx, choice: str, amount: str):
    choice = choice.lower()
    if choice not in ['tai', 'xiu']:
        return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [tiền]`")

    try:
        bet = int(amount)
        if bet <= 0: raise ValueError
    except: return await ctx.send("❌ Số tiền không hợp lệ!")

    data = Database.fetch("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not data or data[0] < bet:
        return await ctx.send("❌ Bạn không đủ tiền trong ví!")

    # Bắt đầu nặn
    embed_roll = discord.Embed(description="🎲 **Đang lắc bát... nặn kịch tính!**", color=0xf1c40f)
    msg = await ctx.send(embed=embed_roll)
    await asyncio.sleep(3) # Thời gian nặn

    dices = [random.randint(1, 6) for _ in range(3)]
    total = sum(dices)
    result = "tai" if total >= 11 else "xiu"
    win = (choice == result)

    change = int(bet * 0.95) if win else -bet
    Database.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (change, ctx.author.id))

    embed_res = discord.Embed(
        title="🎰 KẾT QUẢ TÀI XỈU",
        color=0x2ecc71 if win else 0xe74c3c,
        description=f"🎲 Bộ ba: **{dices[0]} - {dices[1]} - {dices[2]}**\n🎯 Tổng điểm: **{total}** => **{result.upper()}**"
    )
    embed_res.add_field(name="Kết quả:", value=f"{'✨ THẮNG' if win else '💀 THUA'}")
    embed_res.add_field(name="Biến động:", value=f"{'+' if win else ''}{change:,} xu")
    
    await msg.edit(embed=embed_res)

# ==========================================================
# 🏦 QUẢN LÝ VÍ & ADMIN (NẠP / ĐĂNG BÁN)
# ==========================================================
@bot.command()
async def vi(ctx):
    user_id = ctx.author.id
    Database.execute("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (user_id,))
    data = Database.fetch("SELECT coins FROM users WHERE user_id = ?", (user_id,), one=True)
    
    embed = discord.Embed(title="💳 VÍ TIỀN DISCORD", color=0x2f3136)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.add_field(name="👤 Chủ tài khoản", value=ctx.author.mention, inline=False)
    embed.add_field(name="💰 Số dư hiện có", value=f"**{data[0]:,}** xu", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if not any(role.id in ADMIN_ROLES for role in ctx.author.roles):
        return await ctx.send("❌ Bạn không có quyền Admin!")
    
    Database.execute("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
    Database.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
    await ctx.send(f"✅ Đã nạp **{amount:,}** xu cho {member.mention}")

@bot.command()
async def dangban(ctx, price: int, *, item_name: str):
    """Admin đăng bán sản phẩm tại kênh Shop"""
    if not any(role.id in ADMIN_ROLES for role in ctx.author.roles): return
    if ctx.channel.id != ID_KENH_SHOP: return await ctx.send(f"❌ Hãy dùng lệnh này tại <#{ID_KENH_SHOP}>")

    embed_item = discord.Embed(title="🛍️ SẢN PHẨM MỚI LÊN KỆ", color=0x9b59b6)
    embed_item.description = f"### {item_name}\n━━━━━━━━━━━━━━━━━━━━\n💰 Giá: **{price:,}** xu\n\n*Nhấn nút dưới để mua tự động qua ví.*"
    embed_item.set_footer(text="Giao dịch an toàn - Tự động tạo Ticket")
    
    await ctx.send(embed=embed_item, view=PersistentShopView(item_name, price))
    await ctx.message.delete()

# ==========================================================
# 🏆 BẢNG XẾP HẠNG TỰ ĐỘNG
# ==========================================================
@tasks.loop(minutes=10)
async def leaderboard_task():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return

    top_users = Database.fetch("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    embed_lb = discord.Embed(title="🏆 BẢNG XẾP HẠNG ĐẠI GIA", color=0xffd700, timestamp=datetime.now())
    embed_lb.set_thumbnail(url="https://i.imgur.com/8E9S9zY.png")
    
    if not top_users:
        embed_lb.description = "Chưa có dữ liệu người chơi."
    else:
        lb_content = ""
        for i, (uid, coins) in enumerate(top_users, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`#{i}`"
            lb_content += f"{medal} <@{uid}> — `{coins:,}` xu\n"
        embed_lb.description = lb_content

    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed_lb)

# ==========================================================
# 🚀 KHỞI CHẠY BOT
# ==========================================================
@bot.event
async def on_ready():
    init_db()
    football_update_task.start()
    leaderboard_task.start()
    logging.info(f"Bot {bot.user.name} đã sẵn sàng!")

bot.run(TOKEN)
