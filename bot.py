import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import random
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
ADMIN_ROLE_ID = 1465374336214106237 
ID_BXH = 1474674662792232981        
ID_CATEGORY_TICKET = 1474672512708247582 # ID Category để mở Ticket Shop

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('economy.db')
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

history_cau = []

# --- UI: TICKET & HÓA ĐƠN ---
async def create_ticket(interaction, item_name, price):
    guild = interaction.guild
    category = guild.get_channel(ID_CATEGORY_TICKET)
    
    # Tạo ticket với tên vật phẩm
    ticket_channel = await guild.create_text_channel(
        name=f"🛒-{item_name}-{interaction.user.name}",
        category=category,
        overwrites={
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(ADMIN_ROLE_ID): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
    )
    
    # Gửi thông báo trong ticket
    embed_tk = discord.Embed(title="🎫 TICKET MUA HÀNG", color=0x2ecc71)
    embed_tk.description = f"Chào {interaction.user.mention}, bạn đã mua **{item_name}** thành công.\nVui lòng đợi Admin xử lý vật phẩm cho bạn."
    await ticket_channel.send(embed=embed_tk)
    
    # Gửi hóa đơn riêng (DM)
    try:
        receipt = discord.Embed(title="🧾 HÓA ĐƠN VERDICT CASH", color=0xf1c40f)
        receipt.add_field(name="Vật phẩm", value=item_name, inline=True)
        receipt.add_field(name="Giá thanh toán", value=f"{price:,} Cash", inline=True)
        receipt.add_field(name="Mã Ticket", value=ticket_channel.mention, inline=False)
        receipt.set_footer(text=f"Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        await interaction.user.send(embed=receipt)
    except: pass

# --- UI: NÚT BẤM SHOP ---
class ShopView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Mua Role [Đại Gia] - 5M", style=discord.ButtonStyle.primary, custom_id="shop_1")
    async def buy_rich(self, interaction: discord.Interaction, button: ui.Button):
        price = 5000000
        user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user_data or user_data[0] < price:
            return await interaction.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        await interaction.response.send_message("✅ Đã thanh toán! Ticket của bạn đang được mở.", ephemeral=True)
        await create_ticket(interaction, "Role-Dai-Gia", price)

    @ui.button(label="Mua Thẻ Đổi Tên - 1M", style=discord.ButtonStyle.success, custom_id="shop_2")
    async def buy_name(self, interaction: discord.Interaction, button: ui.Button):
        price = 1000000
        user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user_data or user_data[0] < price:
            return await interaction.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)
        
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        await interaction.response.send_message("✅ Đã thanh toán! Ticket của bạn đang được mở.", ephemeral=True)
        await create_ticket(interaction, "The-Doi-Ten", price)

# --- UI: VÍ & LỊCH SỬ ---
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.button(label="📜 Lịch sử cược", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Đây không phải ví của bạn!", ephemeral=True)
        
        history = query_db("SELECT team, amount, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        desc = "".join([f"🔹 **{t}** | `{a:,}` | {s}\n" for t, a, s in history]) if history else "Chưa có dữ liệu."
        await interaction.response.send_message(embed=discord.Embed(title="📜 LỊCH SỬ", description=desc, color=0x3498db), ephemeral=True)

# --- LỆNH TÀI XỈU 55% ---
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_cau
    side = side.lower()
    if amount < 1000: return await ctx.send("❌ Cược tối thiểu 1,000!")
    
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Bạn nghèo quá!")

    is_rigged = random.randint(1, 100) <= 55 
    total = random.randint(3, 18)
    res_text = "tai" if total >= 11 else "xiu"

    if is_rigged and res_text == side:
        total = random.randint(3, 10) if side == "tai" else random.randint(11, 18)
        res_text = "xiu" if total <= 10 else "tai"

    history_cau.append({"res": "T" if res_text == "tai" else "X", "val": total})
    if len(history_cau) > 20: history_cau.pop(0)

    win = (side == res_text)
    change = amount if win else -amount
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (change, ctx.author.id))
    query_db("INSERT INTO bets (user_id, team, amount, status) VALUES (?, ?, ?, ?)", (ctx.author.id, side.upper(), amount, "WIN" if win else "LOSE"))

    embed = discord.Embed(title=f"🎲 KẾT QUẢ: {res_text.upper()} ({total})", color=0x00ff00 if win else 0xff0000)
    embed.description = f"Bạn đã **{'THẮNG' if win else 'THUA'}** `{amount:,}` Cash"
    await ctx.send(embed=embed)

# --- LỆNH SOI CẦU 1-18 ---
@bot.command()
async def cau(ctx):
    if not history_cau: return await ctx.send("📑 Chưa có dữ liệu phiên.")
    graph = ""
    for lvl in range(18, 0, -1):
        line = f"{lvl:02d} ┃"
        for entry in history_cau[-15:]:
            line += " ● " if entry['val'] == lvl else "   "
        graph += line + "\n"
    footer = "   ┗" + "━━━" * 15
    nums = "     " + " ".join([f"{e['res']}{e['val']:02d}" for e in history_cau[-15:]])
    embed = discord.Embed(title="📈 BIỂU ĐỒ SOI CẦU (1-18)", description=f"```\n{graph}{footer}\n{nums}\n```", color=0xffd700)
    await ctx.send(embed=embed)

# --- LỆNH VÍ & NẠP ---
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", color=0x2ecc71)
    embed.description = f"👤 **Chủ ví:** {ctx.author.mention}\n💰 **Số dư:** `{coins:,}` Cash"
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp `{amount:,}` cho {member.mention}")

# --- LỆNH SHOP ---
@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🛒 VERDICT CASH SHOP", color=0x9b59b6)
    embed.description = "Nhấn vào nút bên dưới để mua vật phẩm.\nSau khi mua, hệ thống sẽ mở Ticket xử lý riêng cho bạn."
    embed.add_field(name="💎 Role [Đại Gia]", value="Giá: `5,000,000` Cash", inline=False)
    embed.add_field(name="🎫 Thẻ Đổi Tên", value="Giá: `1,000,000` Cash", inline=False)
    await ctx.send(embed=embed, view=ShopView())

# --- BXH 2 PHÚT ---
@tasks.loop(minutes=2)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=0xf1c40f)
    desc = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (u_id, coins) in enumerate(top):
        m = ["🥇","🥈","🥉","🔹"][i if i<3 else 3]
        desc += f"{m} **Top {i+1}** | <@{u_id}>: `{coins:,}` Cash\n"
    embed.description = desc
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed)

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, team TEXT, amount INTEGER, status TEXT)')
    update_leaderboard.start()
    bot.add_view(ShopView()) # Giữ nút bấm sống sau khi restart
    print(f"🚀 {bot.user.name} đã sẵn sàng!")

bot.run(TOKEN)
