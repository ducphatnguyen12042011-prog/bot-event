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
API_KEY = "YOUR_FOOTBALL_DATA_API_KEY"

# ID CÁC KÊNH
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ID_KENH_SHOP = 1474695449167400972
ID_CATEGORY_TICKET = 1474672512708247582 # Danh mục tạo kênh mua hàng

# ID ROLE ADMIN
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]

# CẤU HÌNH GIẢI ĐẤU (ƯU TIÊN)
BIG_LEAGUES = ['PL', 'CL', 'BL1', 'SA', 'PD', 'FL1']
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
    print("📢 Database đã sẵn sàng!")

# ======================== HỆ THỐNG SHOP TICKET TỰ ĐỘNG ========================
class BuyAction(ui.View):
    def __init__(self, item_name, price):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.price = price

    @ui.button(label="🛒 THANH TOÁN NGAY", style=discord.ButtonStyle.success, custom_id="pay_now")
    async def pay_callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        data = query_db("SELECT coins FROM users WHERE user_id = ?", (user_id,), one=True)
        balance = data[0] if data else 0

        if balance < self.price:
            return await interaction.response.send_message(f"❌ Bạn không đủ xu! Cần `{self.price:,}` xu.", ephemeral=True)

        # Trừ tiền
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (self.price, user_id))
        
        # Tạo Ticket
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        for r_id in ADMIN_ROLES:
            role = guild.get_role(r_id)
            if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        chan = await guild.create_text_channel(name=f"📦-{interaction.user.name}", overwrites=overwrites, category=guild.get_channel(ID_CATEGORY_TICKET))
        
        eb = discord.Embed(title="✅ GIAO DỊCH THÀNH CÔNG", color=0x2ecc71)
        eb.description = f"**Sản phẩm:** {self.item_name}\n**Giá:** `{self.price:,}` xu\n\nAdmin sẽ sớm bàn giao hàng cho bạn tại đây!"
        await chan.send(content=f"{interaction.user.mention} | Admin hỗ trợ", embed=eb)
        await interaction.response.send_message(f"✅ Đã thanh toán! Kiểm tra kênh: {chan.mention}", ephemeral=True)

# ======================== CÁC LỆNH ADMIN & VÍ ========================
@bot.command()
async def dangban(ctx, price: int, *, name: str):
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    if ctx.channel.id != ID_KENH_SHOP: return await ctx.send("❌ Dùng lệnh này tại kênh Shop!")
    
    eb = discord.Embed(title="🛍️ SẢN PHẨM ĐANG BÁN", color=0x9b59b6)
    eb.add_field(name="📦 Tên món hàng", value=f"**{name}**", inline=False)
    eb.add_field(name="💰 Giá niêm yết", value=f"`{price:,}` xu", inline=False)
    eb.set_footer(text="Hệ thống thanh toán tự động qua ví xu")
    await ctx.send(embed=eb, view=BuyAction(name, price))
    await ctx.message.delete()

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    eb = discord.Embed(title="💳 VÍ TIỀN", description=f"Số dư: **{coins:,}** xu", color=0xf1c40f)
    await ctx.send(embed=eb)

@bot.command()
async def nap(ctx, m: discord.Member, amt: int):
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (m.id,))
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, m.id))
    await ctx.send(f"✅ Đã nạp `{amt:,}` xu cho {m.mention}")

# ======================== ⚽ BÓNG ĐÁ: CẬP NHẬT TỈ SỐ & KÈO ========================
class BetModal(ui.Modal, title='🎫 ĐẶT CƯỢC'):
    bet_amt = ui.TextInput(label='Số tiền cược (Tối thiểu 100)', placeholder='Nhập số xu...')
    def __init__(self, mid, team, hdp):
        super().__init__()
        self.mid, self.team, self.hdp = mid, team, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.bet_amt.value)
            if val < 100: raise ValueError
        except: return await interaction.response.send_message("❌ Tiền không hợp lệ!", ephemeral=True)
        
        d = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not d or d[0] < val: return await interaction.response.send_message("❌ Không đủ xu!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp) VALUES (?, ?, ?, ?, ?)", (interaction.user.id, self.mid, val, self.team, self.hdp))
        await interaction.response.send_message(f"✅ Đã cược `{val:,}` cho **{self.team}**", ephemeral=True)

@tasks.loop(minutes=5)
async def auto_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    headers = {"X-Auth-Token": API_KEY}
    url = "https://api.football-data.org/v4/matches"
    
    try:
        req = requests.get(url, headers=headers)
        if req.status_code != 200: return print(f"API Lỗi: {req.status_code}")
        
        data = req.json()
        matches = data.get('matches', [])[:10]
        old_pins = await channel.pins()

        # Dọn dẹp tin nhắn cũ
        await channel.purge(limit=20, check=lambda m: m.author == bot.user and not m.pinned)

        for m in matches:
            status = m['status']
            h_team, a_team = m['homeTeam'], m['awayTeam']
            h_score = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
            a_score = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0
            
            # 🟢 TRẬN SẮP ĐÁ (HÌNH 3 - LOGO 1:1)
            if status in ['SCHEDULED', 'TIMED']:
                hdp = random.choice([0, 0.25, 0.5, 0.75, 1.0])
                t_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
                
                eb = discord.Embed(title=f"⚽ {m['competition']['name']}", color=0x3498db)
                eb.set_author(name=h_team['name'], icon_url=h_team.get('crest'))
                eb.set_thumbnail(url=a_team.get('crest')) # Đối xứng 1:1
                eb.description = (
                    f"### {h_team['name']}  vs  {a_team['name']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏰ **Bắt đầu:** `{t_vn}`\n"
                    f"⚖️ **Kèo chấp:** Chủ chấp `{hdp}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                
                v = ui.View(timeout=None)
                b1 = ui.Button(label=f"Cược {h_team['name']}", style=discord.ButtonStyle.success)
                b2 = ui.Button(label=f"Cược {a_team['name']}", style=discord.ButtonStyle.danger)
                
                b1.callback = lambda i, t=h_team['name'], mid=m['id'], h=hdp: i.response.send_modal(BetModal(mid, t, h))
                b2.callback = lambda i, t=a_team['name'], mid=m['id'], h=hdp: i.response.send_modal(BetModal(mid, t, -h))
                
                v.add_item(b1); v.add_item(b2)
                msg = await channel.send(embed=eb, view=v)
                
                # Ghim nếu là giải lớn
                if m['competition']['code'] in BIG_LEAGUES: await msg.pin()

            # 🔴 TRẬN ĐANG ĐÁ (HÌNH 4)
            elif status in ['IN_PLAY', 'PAUSED']:
                eb = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xff0000)
                eb.set_author(name=h_team['name'], icon_url=h_team.get('crest'))
                eb.set_thumbnail(url=a_team.get('crest'))
                eb.description = f"# {h_score}  —  {a_score}\n━━━━━━━━━━━━━━━━━━━━"
                await channel.send(embed=eb)

            # 🏁 KẾT THÚC (TỰ GỠ GHIM)
            elif status == 'FINISHED':
                for pin in old_pins:
                    if pin.author == bot.user and h_team['name'] in pin.embeds[0].author.name:
                        await pin.unpin()
    except Exception as e: print(f"Lỗi Football: {e}")

# ======================== 🎰 TÀI XỈU NẶN (CHẤT LƯỢNG) ========================
@bot.command()
async def taixiu(ctx, choice: str, amt: int):
    choice = choice.lower()
    if choice not in ['tai', 'xiu']: return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [tiền]`")
    
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not d or d[0] < amt: return await ctx.send("❌ Bạn không đủ xu!")

    msg = await ctx.send(embed=discord.Embed(description="🎰 **Đang lắc bát... hãy chờ nặn!**", color=0xffff00))
    await asyncio.sleep(3)

    dice = [random.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    result = "tai" if total >= 11 else "xiu"
    is_win = (choice == result)
    
    change = int(amt * 0.95) if is_win else -amt
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (change, ctx.author.id))
    
    eb = discord.Embed(title="🎰 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if is_win else 0xe74c3c)
    eb.add_field(name="🎲 Xúc xắc", value=f"**{dice[0]} · {dice[1]} · {dice[2]}**", inline=True)
    eb.add_field(name="🎯 Tổng", value=f"**{total}** ({result.upper()})", inline=True)
    eb.description = f"### {'✨ BẠN THẮNG!' if is_win else '💀 BẠN THUA!'}\nBiến động: `{'+' if is_win else ''}{change:,}` xu"
    await msg.edit(embed=eb)

# ======================== 🏆 BXH TỰ ĐỘNG ========================
@tasks.loop(minutes=10)
async def update_lb():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    eb = discord.Embed(title="🏆 BẢNG VINH DANH ĐẠI GIA", color=0xffd700, timestamp=datetime.now())
    lb_text = ""
    for i, (uid, coins) in enumerate(top, 1):
        medal = ["🥇", "🥈", "🥉", "👤"][i-1] if i <= 3 else "👤"
        lb_text += f"{medal} **Top {i}** | <@{uid}>\n> 💰 Tài sản: `{coins:,}` xu\n"
    
    eb.description = lb_text if lb_text else "Chưa có dữ liệu."
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=eb)

# ======================== KHỞI CHẠY ========================
@bot.event
async def on_ready():
    init_db()
    auto_football.start()
    update_lb.start()
    print(f"🚀 Bot {bot.user} đã sẵn sàng!")

bot.run(TOKEN)
