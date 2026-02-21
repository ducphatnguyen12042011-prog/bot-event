import discord
from discord.ext import commands
from discord import Embed, ButtonStyle, PermissionOverwrite, Interaction
from discord.ui import View, Button, Modal, TextInput
import random
import datetime
import asyncio
import motor.motor_asyncio # Dùng MongoDB để lưu trữ vĩnh viễn

# --- CẤU HÌNH ---
TOKEN = "YOUR_BOT_TOKEN"
MONGO_URL = "YOUR_MONGODB_CONNECTION_STRING" # Lấy từ MongoDB Atlas (miễn phí)
COLOR_VERDICT = 0x00FBFF
LOGO_DEFAULT = "https://i.imgur.com/your_logo.png"

# Dữ liệu sức mạnh AI (Power Ranking)
TEAM_DATA = {
    "Real Madrid": {"p": 95, "logo": "https://i.imgur.com/Gis6Snd.png", "rank": 1},
    "Man City": {"p": 96, "logo": "https://i.imgur.com/8N4N3u8.png", "rank": 2},
    "Liverpool": {"p": 93, "logo": "https://i.imgur.com/9nFvT8O.png", "rank": 3},
    "Barca": {"p": 89, "logo": "https://i.imgur.com/7S8p3Yj.png", "rank": 4},
    "MU": {"p": 84, "logo": "https://i.imgur.com/6YpS6pG.png", "rank": 8}
}

# --- DATABASE CONNECTION ---
cluster = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = cluster["verdict_bot"]
users_col = db["users"]
matches_col = db["matches"]
global_col = db["global"]

class VerdictBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def on_ready(self):
        print(f"✨ {self.user} đã sẵn sàng trên Railway!")

bot = VerdictBot()

# --- UTILS ---
async def get_user_data(uid):
    user = await users_col.find_one({"_id": str(uid)})
    if not user:
        user = {"_id": str(uid), "cash": 5000, "logs": ["+5,000 (Quà khởi nghiệp)"]}
        await users_col.insert_one(user)
    return user

async def update_cash(uid, amount, reason):
    await users_col.update_one(
        {"_id": str(uid)},
        {"$inc": {"cash": amount}, "$push": {"logs": f"{reason}: {'+' if amount > 0 else ''}{amount:,}"}}
    )

# --- UI: TICKET SYSTEM ---
class ShopTicketView(View):
    def __init__(self, item_name, price):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.price = price

    @discord.ui.button(label="XÁC NHẬN ĐỔI", style=ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: Interaction, button: Button):
        user = await get_user_data(interaction.user.id)
        if user["cash"] < self.price:
            return await interaction.response.send_message("❌ Bạn không đủ Verdict Cash!", ephemeral=True)
        
        await update_cash(interaction.user.id, -self.price, f"Mua {self.item_name}")
        
        # Tạo Ticket và đổi tên
        overwrites = {
            interaction.guild.default_role: PermissionOverwrite(read_messages=False),
            interaction.user: PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel_name = f"📦-{self.item_name.replace(' ', '-').lower()}"
        channel = await interaction.guild.create_text_channel(name=channel_name, overwrites=overwrites)
        
        embed = Embed(title="🎫 VERDICT SHOP TICKET", color=COLOR_VERDICT)
        embed.add_field(name="Sản phẩm", value=f"**{self.item_name}**", inline=True)
        embed.add_field(name="Khách hàng", value=interaction.user.mention, inline=True)
        
        await channel.send(content=f"@here", embed=embed)
        await interaction.response.send_message(f"✅ Đã tạo ticket tại {channel.mention}", ephemeral=True)

# --- UI: WALLET BUTTONS ---
class WalletView(View):
    def __init__(self, uid):
        super().__init__(timeout=None)
        self.uid = uid

    @discord.ui.button(label="Lịch sử giao dịch", style=ButtonStyle.secondary, emoji="📜")
    async def history(self, interaction: Interaction, button: Button):
        user = await get_user_data(self.uid)
        logs = "\n".join(user["logs"][-8:])
        await interaction.response.send_message(f"📜 **Giao dịch gần đây:**\n{logs}", ephemeral=True)

# --- COMMANDS: ECONOMY ---
@bot.command()
async def vi(ctx):
    user = await get_user_data(ctx.author.id)
    embed = Embed(title="💳 VÍ VERDICT CASH", color=COLOR_VERDICT)
    embed.add_field(name="💰 Số dư", value=f"**{user['cash']:,}** V-Cash", inline=False)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, member: discord.Member, amount: int):
    await update_cash(member.id, amount, "Admin nạp")
    await ctx.send(f"✅ Đã nạp `{amount:,}` V-Cash cho {member.mention}")

# --- COMMANDS: BÓNG ĐÁ & AI SETTLEMENT ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setmatch(ctx, team1: str, team2: str):
    # Smart AI tự động điền kèo
    t1_data = TEAM_DATA.get(team1, {"p": 80, "logo": LOGO_DEFAULT, "rank": 10})
    t2_data = TEAM_DATA.get(team2, {"p": 80, "logo": LOGO_DEFAULT, "rank": 10})
    
    diff = (t1_data["p"] - t2_data["p"]) + (t2_data["rank"] - t1_data["rank"]) * 0.5
    handicap = round(diff / 5 * 4) / 4
    match_id = str(random.randint(1000, 9999))
    
    await matches_col.insert_one({
        "_id": match_id, "t1": team1, "t2": team2, "h": handicap, "bets": []
    })

    embed = Embed(title="⚽ KÈO BÓNG ĐÁ SETTLEMENT AI", color=COLOR_VERDICT)
    embed.set_thumbnail(url=t1_data["logo"])
    embed.add_field(name=f"🏠 {team1}", value=f"Hạng: {t1_data['rank']}", inline=True)
    embed.add_field(name=f"✈️ {team2}", value=f"Hạng: {t2_data['rank']}", inline=True)
    embed.add_field(name="⚖️ KÈO CHẤP", value=f"**{team1}** chấp **{handicap}** trái", inline=False)
    embed.set_footer(text=f"ID: {match_id} | !cuoc {match_id} [t1/t2] [tiền]")
    await ctx.send(embed=embed)

@bot.command()
async def cuoc(ctx, m_id: str, side: str, amount: int):
    match = await matches_col.find_one({"_id": m_id})
    if not match: return await ctx.send("❌ Trận đấu không tồn tại!")
    
    user = await get_user_data(ctx.author.id)
    if amount > user["cash"] or amount < 100: return await ctx.send("❌ Tiền cược không hợp lệ!")

    await update_cash(ctx.author.id, -amount, f"Cược trận {m_id}")
    await matches_col.update_one({"_id": m_id}, {"$push": {"bets": {"uid": str(ctx.author.id), "side": side, "amount": amount}}})
    
    # Gửi vé DM
    dm_embed = Embed(title="🎟️ VÉ CƯỢC VERDICT XÁC NHẬN", color=COLOR_VERDICT)
    dm_embed.add_field(name="Trận", value=f"{match['t1']} vs {match['t2']}")
    dm_embed.add_field(name="Kèo", value=f"{match['t1']} chấp {match['h']}")
    dm_embed.add_field(name="Đặt", value=f"Đội {side.upper()} | {amount:,} V-Cash")
    try: await ctx.author.send(embed=dm_embed)
    except: pass
    await ctx.send(f"✅ {ctx.author.mention} đã cược thành công! Check DM.")

@bot.command()
@commands.has_permissions(administrator=True)
async def settle(ctx, m_id: str, s1: int, s2: int):
    match = await matches_col.find_one({"_id": m_id})
    if not match: return
    
    result = (s1 - match["h"]) - s2 # Kết quả thực tế sau chấp
    
    for b in match["bets"]:
        if (b["side"] == "t1" and result > 0) or (b["side"] == "t2" and result < 0):
            win_amount = int(b["amount"] * 1.95)
            await update_cash(b["uid"], win_amount, f"Thắng kèo {m_id}")
        elif result == 0:
            await update_cash(b["uid"], b["amount"], f"Hoàn tiền kèo {m_id}")
            
    await matches_col.delete_one({"_id": m_id})
    await ctx.send(f"🏁 Trận {match['t1']} vs {match['t2']} ({s1}-{s2}) đã quyết toán xong!")

# --- COMMANDS: TÀI XỈU 53% ---
@bot.command()
async def taixiu(ctx, side: str, amount: str):
    user = await get_user_data(ctx.author.id)
    side = side.lower()
    bet = user["cash"] if amount == "all" else int(amount)
    
    if bet < 100 or bet > user["cash"]: return await ctx.send("❌ Tiền không hợp lệ!")

    # Logic 53% thua
    win = random.random() < 0.47
    d1, d2, d3 = [random.randint(1,6) for _ in range(3)]
    total = sum(d1+d2+d3)
    real_side = "tai" if total >= 11 else "xiu"
    
    # Cập nhật cầu
    await global_col.update_one({"_id": "history"}, {"$push": {"data": {"$each": ["🔴" if real_side == "tai" else "🔵"], "$slice": -20}}}, upsert=True)

    if win and side in real_side:
        await update_cash(ctx.author.id, bet, "Thắng Tài Xỉu")
        msg, color = f"🎉 THẮNG! +{bet:,}", 0x2ecc71
    else:
        await update_cash(ctx.author.id, -bet, "Thua Tài Xỉu")
        msg, color = f"💸 THUA! -{bet:,}", 0xe74c3c

    embed = Embed(title="🎲 TÀI XỈU VERDICT", description=f"{msg}\nKết quả: **{real_side.upper()}** ({total})", color=color)
    embed.add_field(name="Xúc xắc", value=f"🎲 {d1} {d2} {d3}")
    await ctx.send(embed=embed)

@bot.command()
async def soicau(ctx):
    hist = await global_col.find_one({"_id": "history"})
    cau = "".join(hist["data"]) if hist else "Trống"
    await ctx.send(embed=Embed(title="📊 SOI CẦU (20 PHIÊN)", description=f"`{cau}`", color=COLOR_VERDICT))

# --- COMMANDS: SHOP & BXH ---
@bot.command()
async def shop(ctx):
    embed = Embed(title="🛒 SHOP VERDICT CASH", description="Chọn sản phẩm bằng nút dưới:", color=COLOR_VERDICT)
    embed.add_field(name="💎 VIP Role", value="Giá: 100,000 V-Cash", inline=False)
    
    view = View()
    btn = Button(label="Mua VIP Role", style=ButtonStyle.primary)
    btn.callback = lambda i: i.response.send_message("Xác nhận đổi?", view=ShopTicketView("VIP Role", 100000), ephemeral=True)
    view.add_item(btn)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def bxh(ctx):
    cursor = users_col.find().sort("cash", -1).limit(10)
    top_list = await cursor.to_list(length=10)
    
    embed = Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=COLOR_VERDICT)
    desc = ""
    for i, u in enumerate(top_list):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "🔹"
        desc += f"{medal} <@{u['_id']}>: `{u['cash']:,}` V-Cash\n"
    embed.description = desc
    await ctx.send(embed=embed)

bot.run(TOKEN))
