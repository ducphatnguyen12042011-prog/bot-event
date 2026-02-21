import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ADMIN_ROLE_ID = 1465374336214106237 # Thay ID Role Admin của bạn
ID_BXH = 1474674662792232981        # Thay ID Kênh BXH
ID_BONG_DA = 1474672512708247582    # Thay ID Kênh soi kèo

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
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

current_matches = {}

# ================= SHOP ITEMS =================
SHOP_ITEMS = {
    "1": {"name": "Danh hiệu: Đại Gia", "price": 50000, "role_id": 123456789},
    "2": {"name": "Danh hiệu: Thần Lô", "price": 100000, "role_id": 987654321},
    "3": {"name": "Thẻ Đổi Màu Tên", "price": 25000, "role_id": None}
}

# ================= UI: NÚT BẤM LỊCH SỬ =================
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.button(label="📜 Xem lịch sử đặt cược", style=discord.ButtonStyle.grey)
    async def history(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Đây không phải ví của bạn!", ephemeral=True)
        
        # Lấy lịch sử cả bóng đá và tài xỉu
        history = query_db("SELECT team, amount, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        if not history:
            return await interaction.response.send_message("📭 Bạn chưa có lịch sử đặt cược.", ephemeral=True)
        
        embed = discord.Embed(title="📜 LỊCH SỬ ĐẶT CƯỢC GẦN ĐÂY", color=0x3498db)
        desc = ""
        for team, amt, status in history:
            icon = "⏳" if status == "PENDING" else ("✅" if "WIN" in status or "DONE" in status else "❌")
            desc += f"{icon} **{team}** | Tiền: `{amt:,}` | KQ: `{status}`\n"
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= 1. TỰ ĐỘNG HIỂN THỊ TRẬN ĐẤU (LOGO ĐỀU) =================
@tasks.loop(minutes=15)
async def auto_update_matches():
    global current_matches
    channel = bot.get_channel(ID_BONG_DA)
    if not channel or not API_KEY: return
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": API_KEY}).json()
        matches = res.get('matches', [])[:5]
        current_matches = {str(m['id']): m for m in matches}
        await channel.purge(limit=15, check=lambda m: m.author == bot.user)
        for mid, m in current_matches.items():
            h_name, a_name = m['homeTeam']['name'], m['awayTeam']['name']
            h_icon, a_icon = m['homeTeam'].get('crest'), m['awayTeam'].get('crest')
            h_score = m['score']['fullTime']['home'] or 0
            a_score = m['score']['fullTime']['away'] or 0
            embed = discord.Embed(title=f"⚽ {h_score}  -  {a_score} ⚽", color=0x2f3136)
            embed.set_author(name=h_name, icon_url=h_icon)
            embed.set_thumbnail(url=a_icon)
            embed.description = f"**{h_name} vs {a_name}**\n⚖️ Kèo: **{h_name} chấp 0.5**"
            embed.add_field(name="🆔 Mã trận", value=f"`{mid}`", inline=True)
            embed.set_footer(text="!cuoc <mã> <chu/khach> <tiền>")
            await channel.send(embed=embed)
    except: pass

# ================= 2. LỆNH ĐẶT CƯỢC & GỬI VÉ DM =================
@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    if match_id not in current_matches: return await ctx.send("❌ Mã trận không tồn tại!")
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Bạn không đủ tiền!")

    match = current_matches[match_id]
    team_bet = match['homeTeam']['name'] if side.lower() in ["chu", "home"] else match['awayTeam']['name']
    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, ?, ?, ?, 0.5, 'PENDING')", 
             (ctx.author.id, match_id, amount, team_bet))

    await ctx.send("✅ Đã chốt kèo! Kiểm tra DM nhận vé.")
    try:
        embed = discord.Embed(title="🎟️ VÉ CƯỢC BÓNG ĐÁ", color=0x3498db)
        embed.add_field(name="🏟️ Trận", value=f"{match['homeTeam']['name']} vs {match['awayTeam']['name']}", inline=False)
        embed.add_field(name="🚩 Đội đặt", value=f"`{team_bet}`", inline=True)
        embed.add_field(name="💰 Tiền cược", value=f"`{amount:,}`", inline=True)
        embed.set_footer(text=f"Thời gian: {datetime.now().strftime('%H:%M:%S')}")
        await ctx.author.send(embed=embed)
    except: pass

# ================= 3. LỆNH VÍ & NẠP TIỀN =================
@bot.command()
async def vi(ctx):
    data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = data[0] if data else 0
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", description=f"Số dư: **{coins:,}** Verdict Cash", color=0x2ecc71)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** cho {member.mention}")

# ================= 4. BẢNG XẾP HẠNG (BXH) =================
@tasks.loop(minutes=20)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=0xf1c40f)
    desc = ""
    for i, (uid, coins) in enumerate(top):
        medals = ["🥇", "🥈", "🥉", "🏅"]
        m = medals[i] if i < 3 else medals[3]
        desc += f"{m} **Top {i+1}** | <@{uid}>: `{coins:,}` Cash\n"
    embed.description = desc
    await channel.purge(limit=2); await channel.send(embed=embed)

# ================= 5. TÀI XỈU (KỊCH TÍNH) =================
@bot.command()
async def taixiu(ctx, side: str, amount: int):
    side = side.lower()
    if side not in ['tai', 'xiu']: return await ctx.send("❌ Chọn `tai` hoặc `xiu`!")
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Bạn không đủ tiền!")

    dices = [random.randint(1, 6) for _ in range(3)]
    total = sum(dices)
    result = "tai" if total >= 11 else "xiu"
    
    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    
    msg = await ctx.send(f"🎲 **{ctx.author.name}** đang lắc xúc xắc...")
    import asyncio
    await asyncio.sleep(2)
    
    color = 0x00ff00 if side == result else 0xff0000
    status = "WIN" if side == result else "LOSE"
    if status == "WIN":
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount * 2, ctx.author.id))
    
    query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp, status) VALUES (?, 'TAI_XIU', ?, ?, 0, ?)", 
             (ctx.author.id, amount, side.upper(), status))

    embed = discord.Embed(title=f"🎲 KẾT QUẢ: {result.upper()} ({total})", color=color)
    embed.description = f"Xúc xắc: {' '.join(map(str, dices))}\n\nBạn đã **{status}** {'`+'+str(amount)+'`' if status == 'WIN' else '`-'+str(amount)+'`'} Verdict Cash"
    await msg.edit(content=None, embed=embed)

# ================= 6. SHOP VẬT PHẨM =================
@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🏪 SHOP ĐỔI ITEM VERDICT", color=0x9b59b6)
    for k, v in SHOP_ITEMS.items():
        embed.add_field(name=f"[{k}] {v['name']}", value=f"Giá: `{v['price']:,}` Cash", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def mua(ctx, item_id: str):
    if item_id not in SHOP_ITEMS: return await ctx.send("❌ Mã sai!")
    item = SHOP_ITEMS[item_id]
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < item['price']: return await ctx.send("❌ Bạn không đủ tiền!")

    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (item['price'], ctx.author.id))
    await ctx.send(f"✅ Bạn đã mua thành công **{item['name']}**!")

# ================= KHỞI CHẠY =================
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL, status TEXT)')
    auto_update_matches.start()
    update_leaderboard.start()
    print(f"✅ {bot.user.name} ĐÃ SẴN SÀNG!")

bot.run(TOKEN)
