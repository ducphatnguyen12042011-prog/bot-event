import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ADMIN_ROLE_ID = 1465374336214106237 
ID_BXH = 1474674662792232981        
ID_BONG_DA = 1474672512708247582    
ID_CATEGORY_TICKET = 1474672512708247582 

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

history_points = []

# ================= 1. SHOP & TICKET TỰ ĐỘNG =================
class ShopView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def handle_purchase(self, interaction: discord.Interaction, item_name: str, price: int):
        data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        coins = data[0] if data else 0
        
        if coins < price:
            return await interaction.response.send_message(f"❌ Bạn không đủ tiền! Cần `{price:,}`", ephemeral=True)

        # Trừ tiền
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))

        # Tạo Ticket và đổi tên theo vật phẩm
        guild = interaction.guild
        category = guild.get_channel(ID_CATEGORY_TICKET)
        ticket_name = f"🛒-{item_name}-{interaction.user.name}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(ADMIN_ROLE_ID): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        ticket = await guild.create_text_channel(name=ticket_name, category=category, overwrites=overwrites)
        
        # Thông báo trong Ticket
        emb = discord.Embed(title="🎫 ĐƠN HÀNG MỚI", color=0x2ecc71)
        emb.description = f"{interaction.user.mention} đã mua **{item_name}**\nGiá: `{price:,}` Cash"
        await ticket.send(content=f"<@&{ADMIN_ROLE_ID}>", embed=emb)

        # Gửi hóa đơn DM
        try:
            receipt = discord.Embed(title="🧾 HÓA ĐƠN VERDICT CASH", color=0xf1c40f)
            receipt.add_field(name="Vật phẩm", value=item_name, inline=True)
            receipt.add_field(name="Giá", value=f"{price:,}", inline=True)
            receipt.set_footer(text="Cảm ơn bạn đã mua hàng!")
            await interaction.user.send(embed=receipt)
        except: pass

        await interaction.response.send_message(f"✅ Thành công! Ticket: {ticket.mention}", ephemeral=True)

    @ui.button(label="Mua Role [Đại Gia] - 5M", style=discord.ButtonStyle.primary, custom_id="shop_1")
    async def buy_1(self, i, b): await self.handle_purchase(i, "Role-Dai-Gia", 5000000)

    @ui.button(label="Thẻ Đổi Tên - 1M", style=discord.ButtonStyle.success, custom_id="shop_2")
    async def buy_2(self, i, b): await self.handle_purchase(i, "The-Doi-Ten", 1000000)

# ================= 2. VÍ & LỊCH SỬ BUTTON =================
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.button(label="📜 Lịch sử cược", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Không phải ví của bạn!", ephemeral=True)
        
        history = query_db("SELECT team, amount, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        desc = "".join([f"🔹 **{t}** | `{a:,}` | {s}\n" for t, a, s in history]) if history else "Chưa có dữ liệu."
        await interaction.response.send_message(embed=discord.Embed(title="📜 LỊCH SỬ", description=desc, color=0x3498db), ephemeral=True)

# ================= 3. TÀI XỈU 55% & SOI CẦU LINE =================
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_points
    side = side.lower()
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Bạn không đủ tiền!")

    is_rigged = random.randint(1, 100) <= 55 
    d1, d2, d3 = [random.randint(1, 6) for _ in range(3)]
    total = d1 + d2 + d3
    res_text = "tai" if total >= 11 else "xiu"

    if is_rigged and res_text == side:
        total = random.randint(3, 10) if side == "tai" else random.randint(11, 18)
        d1 = random.randint(1, min(6, total-2))
        d2 = random.randint(1, min(6, total-d1-1))
        d3 = total - d1 - d2
        res_text = "xiu" if total <= 10 else "tai"

    history_points.append(total)
    if len(history_points) > 20: history_points.pop(0)

    win = (side == res_text)
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount if win else -amount, ctx.author.id))

    embed = discord.Embed(title="🎉 Kết quả phiên tài xỉu 🪙", color=0x9b59b6)
    val_str = f"🎲 **Xúc xắc 1** 🎲 **Xúc xắc 2** 🎲 **Xúc xắc 3**\n` {d1} `            ` {d2} `            ` {d3} `\n\n"
    val_str += f"🎯 **Tổng số điểm**: ` {total} `\n📝 **Kết quả**: **{res_text.upper()}**\n"
    val_str += f"💰 Bạn đã **{'THẮNG' if win else 'THUA'}** `{amount:,}` Cash"
    embed.description = val_str
    await ctx.send(embed=embed)

@bot.command()
async def cau(ctx):
    if not history_points: return await ctx.send("📑 Chưa có dữ liệu.")
    points = history_points[-15:]
    graph = ""
    for lvl in [18, 15, 12, 9, 6, 3]:
        line = f"{lvl:02d} ┃"
        for p in points:
            line += " ● " if abs(p - lvl) <= 1 else " ──"
        graph += line + "\n"
    embed = discord.Embed(title="📊 BIỂU ĐỒ SOI CẦU TÀI XỈU", description=f"```\n{graph}```", color=0xffd700)
    await ctx.send(embed=embed)

# ================= 4. BÓNG ĐÁ & VÉ CƯỢC DM =================
@tasks.loop(minutes=10)
async def auto_update_matches():
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:3]
        await channel.purge(limit=10, check=lambda m: m.author == bot.user)

        for m in matches:
            h_name, a_name = m['homeTeam']['shortName'], m['awayTeam']['shortName']
            h_icon, a_icon = m['homeTeam'].get('crest'), m['awayTeam'].get('crest')
            h_score, a_score = (m['score']['fullTime']['home'] or 0), (m['score']['fullTime']['away'] or 0)

            embed = discord.Embed(title="🏆 THÔNG TIN TRẬN ĐẤU ĐANG DIỄN RA 🏆", color=0x2b2d31)
            embed.set_author(name=f"{h_name}", icon_url=h_icon)
            embed.set_thumbnail(url=a_icon)
            embed.add_field(name="📊 TỈ SỐ HIỆN TẠI", value=f"```py\n{h_name} {h_score} — {a_score} {a_name}\n```", inline=False)
            embed.add_field(name="🏠 CHỦ", value=f"**{h_name}**\n`- 0.5`", inline=True)
            embed.add_field(name="✈️ KHÁCH", value=f"**{a_name}**\n`+ 0.5`", inline=True)
            status = "🔴 Đang đá" if m['status'] == "IN_PLAY" else "🕒 Sắp đá"
            embed.add_field(name="📝 CHI TIẾT", value=f"Trạng thái: `{status}` | ID: `{m['id']}`", inline=False)
            await channel.send(embed=embed)
    except: pass

@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Không đủ tiền!")

    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    query_db("INSERT INTO bets (user_id, team, amount, status) VALUES (?, ?, ?, ?)", (ctx.author.id, f"Trận {match_id}", amount, "PENDING"))

    await ctx.send(f"✅ {ctx.author.mention} Đã nhận cược! Check DM để nhận vé.")
    try:
        ticket = discord.Embed(title="🎫 VÉ CƯỢC VERDICT", color=0x3498db)
        ticket.add_field(name="Mã trận", value=match_id, inline=True)
        ticket.add_field(name="Lựa chọn", value=side.upper(), inline=True)
        ticket.add_field(name="Tiền cược", value=f"{amount:,}", inline=True)
        await ctx.author.send(embed=ticket)
    except: pass

# ================= 5. BXH & VÍ =================
@tasks.loop(minutes=2)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=0xf1c40f)
    desc = "".join([f"🔹 **Top {i+1}** | <@{u}>: `{c:,}` Cash\n" for i, (u, c) in enumerate(top)])
    embed.description = f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{desc}"
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", description=f"Số dư: **{d[0] if d else 0:,}** Cash", color=0x2ecc71)
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
async def shop(ctx):
    await ctx.send(embed=discord.Embed(title="🛒 SHOP VERDICT", color=0x9b59b6, description="Mua vật phẩm bằng nút bấm:"), view=ShopView())

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, team TEXT, amount INTEGER, status TEXT)')
    auto_update_matches.start()
    update_leaderboard.start()
    bot.add_view(ShopView())
    print("🚀 Bot Verdict Cash Đã Sẵn Sàng!")

bot.run(TOKEN)
