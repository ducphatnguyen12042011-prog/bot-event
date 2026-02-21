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
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]
ID_CATEGORY_TICKET = 1474672512708247582 # Thay bằng ID danh mục bạn muốn hiện Ticket
DB_PATH = 'economy.db'
BIG_LEAGUES = ['PL', 'CL', 'BL1', 'SA', 'PD', 'FL1'] # Các giải ưu tiên ghim

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE ENGINE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# --- MODAL ĐẶT CƯỢC ---
class BettingModal(ui.Modal, title='🎫 XÁC NHẬN VÀO KÈO'):
    amount = ui.TextInput(label='Tiền cược (Tối thiểu 100)', placeholder='Nhập số xu...', min_length=1)
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
        query_db("INSERT INTO bets (match_id, user_id, amount, choice, hdp) VALUES (?, ?, ?, ?, ?)", (self.m_id, interaction.user.id, amt, self.choice, self.hdp))
        await interaction.response.send_message(f"✅ Đã cược **{amt:,}** xu cho **{self.team}**", ephemeral=True)

# --- HỆ THỐNG SHOP TICKET ---
class TicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🛒 Mua Acc / Cày Thuê", style=discord.ButtonStyle.success, custom_id="shop_ticket", emoji="💎")
    async def create_ticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        for r_id in ADMIN_ROLES:
            role = guild.get_role(r_id)
            if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        chan = await guild.create_text_channel(f"ticket-{interaction.user.name}", overwrites=overwrites, category=guild.get_channel(ID_CATEGORY_TICKET))
        embed = discord.Embed(title="🎫 TICKET HỖ TRỢ", description=f"Chào {interaction.user.mention}, vui lòng nêu yêu cầu tại đây.", color=0x2ecc71)
        m = await chan.send(content=f"{interaction.user.mention} | Admin hỗ trợ", embed=embed)
        await m.pin()
        await interaction.response.send_message(f"✅ Đã tạo kênh: {chan.mention}", ephemeral=True)

# --- ⚽ BÓNG ĐÁ: LOGO 1:1, GHIM/GỠ GHIM, GIAO DIỆN CHUẨN ---
@tasks.loop(minutes=5)
async def auto_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])[:8]
        old_pins = await channel.pins()
        await channel.purge(limit=15, check=lambda m: m.author == bot.user and not m.pinned)

        for m in matches:
            status, h_team, a_team = m['status'], m['homeTeam'], m['awayTeam']
            h_score = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
            a_score = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0
            
            # GIAO DIỆN SẮP ĐÁ (HÌNH 3)
            if status == 'SCHEDULED':
                hdp = random.choice([0, 0.5, 1.0])
                time_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
                embed = discord.Embed(color=0x2ecc71)
                embed.set_author(name=f"🏆 {m['competition']['name']}", icon_url=h_team.get('crest'))
                embed.set_thumbnail(url=a_team.get('crest')) # Logo 1:1 cân bằng
                embed.description = f"### 🏟️ {h_team['name']}  vs  {a_team['name']}\n━━━━━━━━━━━━\n⏰ **Giờ:** `{time_vn}`\n⚖️ **Kèo:** Chấp `{hdp}`"
                
                view = ui.View(timeout=None)
                btn_h = ui.Button(label=f"{h_team['name']} (-{hdp})", style=discord.ButtonStyle.success)
                btn_a = ui.Button(label=f"{a_team['name']} (+{hdp})", style=discord.ButtonStyle.danger)
                
                async def press(i, t, c, h): await i.response.send_modal(BettingModal(m['id'], t, c, h))
                btn_h.callback = lambda i, t=h_team['name'], c=0, h=hdp: press(i, t, c, h)
                btn_a.callback = lambda i, t=a_team['name'], c=1, h=hdp: press(i, t, c, h)
                view.add_item(btn_h); view.add_item(btn_a)

                msg = await channel.send(embed=embed, view=view)
                if m['competition']['code'] in BIG_LEAGUES: await msg.pin()

            # GIAO DIỆN ĐANG ĐÁ (HÌNH 4)
            elif status in ['IN_PLAY', 'FINISHED']:
                color = 0xff0000 if status == 'IN_PLAY' else 0x7f8c8d
                title = "🔴 ĐANG THI ĐẤU" if status == 'IN_PLAY' else "🏁 KẾT THÚC"
                embed = discord.Embed(title=f"{m['competition']['name']} · {title}", color=color)
                embed.set_author(name=h_team['name'], icon_url=h_team.get('crest'))
                embed.set_thumbnail(url=a_team.get('crest'))
                embed.description = f"# {h_score}  —  {a_score}\n━━━━━━━━━━━━"
                
                await channel.send(embed=embed)
                if status == 'FINISHED':
                    for pin in old_pins:
                        if pin.author == bot.user and h_team['name'] in pin.embeds[0].author.name:
                            await pin.unpin()
    except: pass

# --- 🎲 TÀI XỈU ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: str):
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']: return await ctx.send("❌ Chọn `tai` hoặc `xiu`!")
    try: amt = int(cuoc)
    except: return
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not d or d[0] < amt: return await ctx.send("❌ Hết tiền!")

    msg = await ctx.send(embed=discord.Embed(title="🎲 ĐANG LẮC XÚC XẮC...", color=0xffff00))
    await asyncio.sleep(3)
    x = [random.randint(1, 6) for _ in range(3)]
    tong = sum(x)
    kq = "tai" if tong >= 11 else "xiu"
    win = (lua_chon == kq)
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(amt * 0.95) if win else -amt, ctx.author.id))
    
    embed = discord.Embed(title="🎰 KẾT QUẢ", color=0x2ecc71 if win else 0xe74c3c)
    embed.description = f"🎲 Xúc xắc: **{x}** = **{tong}** ({kq.upper()})\n\n{'✅ THẮNG!' if win else '❌ THUA!'}"
    await msg.edit(embed=embed)

# --- 💳 LỆNH VÍ & NẠP ---
@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    await ctx.send(embed=discord.Embed(title="💳 VÍ TIỀN", description=f"Số dư: **{d[0] if d else 0:,}** xu", color=0xf1c40f))

@bot.command()
async def nap(ctx, m: discord.Member, amt: int):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (m.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, m.id))
        await ctx.send(f"✅ Đã nạp {amt:,} xu cho {m.mention}")

@bot.command()
async def setupshop(ctx):
    if not any(r.id in ADMIN_ROLES for r in ctx.author.roles): return
    embed = discord.Embed(title="🛒 SHOP GIAO DỊCH TỰ ĐỘNG", description="Nhấn nút dưới để mở Ticket hỗ trợ.", color=0x3498db)
    await ctx.send(embed=embed, view=TicketView())

# --- KHỞI CHẠY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, user_id INTEGER, amount INTEGER, choice INTEGER, hdp REAL, status INTEGER DEFAULT 0)')
    auto_football.start()
    bot.add_view(TicketView())
    print(f"🔥 {bot.user} đã sẵn sàng!")

bot.run(TOKEN)
