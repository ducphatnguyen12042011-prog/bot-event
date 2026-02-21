import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
from datetime import datetime, timedelta

# --- CẤU HÌNH HỆ THỐNG ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]
DB_PATH = '/app/economy.db'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Cần thiết để lấy danh sách Admin
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- KHỞI TẠO DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS shop (item_name TEXT PRIMARY KEY, price INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item_name TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS bets 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, user_id INTEGER, 
                  amount INTEGER, choice INTEGER, hdp REAL, status INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def update_db(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    conn.close()

# --- PHÂN QUYỀN ---
def is_admin():
    async def predicate(ctx):
        return any(role.id in ADMIN_ROLES for role in ctx.author.roles)
    return commands.check(predicate)

# --- HỆ THỐNG ĐẶT CƯỢC (MODAL) ---
class BettingModal(ui.Modal, title='🎫 XÁC NHẬN ĐẶT CƯỢC'):
    bet_input = ui.TextInput(label='Số tiền cược', placeholder='Nhập số xu (VD: 1000)', min_length=1)

    def __init__(self, match_id, team_name, choice, hdp):
        super().__init__()
        self.match_id, self.team_name, self.choice, self.hdp = match_id, team_name, choice, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.bet_input.value)
            if amt < 100: raise ValueError
        except:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ (Tối thiểu 100)!", ephemeral=True)

        conn = sqlite3.connect(DB_PATH)
        user = conn.execute("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,)).fetchone()
        balance = user[0] if user else 0
        
        if balance < amt:
            return await interaction.response.send_message(f"❌ Bạn không đủ tiền! (Ví: {balance:,})", ephemeral=True)

        update_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, interaction.user.id))
        update_db("INSERT INTO bets (match_id, user_id, amount, choice, hdp) VALUES (?, ?, ?, ?, ?)", 
                  (self.match_id, interaction.user.id, amt, self.choice, self.hdp))
        
        embed = discord.Embed(title="✅ ĐẶT CƯỢC THÀNH CÔNG", color=0x2ecc71)
        embed.description = f"🏟️ Trận ID: `{self.match_id}`\n🚩 Đặt vào: **{self.team_name}**\n💰 Số tiền: `{amt:,}` Coins\n⚖️ Kèo chấp: `{self.hdp}`"
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- ⚽ LIVESCORE & NÚT BẤM CƯỢC ---
@tasks.loop(minutes=5)
async def auto_update_matches():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=SCHEDULED,IN_PLAY", headers=headers).json()
        matches = res.get('matches', [])[:6]
        
        await channel.purge(limit=25, check=lambda m: m.author == bot.user)
        
        for m in matches:
            h_team = m['homeTeam']
            a_team = m['awayTeam']
            h_name, a_name = h_team['name'], a_team['name']
            h_logo, a_logo = h_team.get('crest'), a_team.get('crest')
            hdp = random.choice([0, 0.25, 0.5, 0.75, 1.0]) # Kèo giả lập logic nhà cái

            embed = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x00ffcc)
            embed.set_thumbnail(url=h_logo if h_logo else "")
            embed.set_author(name=f"🆚 {a_name}", icon_url=a_logo if a_logo else "")
            
            status = "🔴 ĐANG ĐÁ" if m['status'] == 'IN_PLAY' else "🟢 SẮP ĐÁ"
            time_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
            
            embed.description = f"**{status}**\n🏟️ **{h_name}** vs **{a_name}**\n⏰ Khởi tranh: `{time_vn}`\n⚖️ Kèo: Đội nhà chấp `{hdp}`"
            embed.set_footer(text=f"Match ID: {m['id']} • Nhấn nút bên dưới để vào kèo")

            view = ui.View(timeout=None)
            btn_h = ui.Button(label=f"Cược {h_name}: -{hdp}", style=discord.ButtonStyle.success)
            btn_h.callback = lambda i, mid=m['id'], tn=h_name, c=0, h=hdp: i.response.send_modal(BettingModal(mid, tn, c, h))
            
            btn_a = ui.Button(label=f"Cược {a_name}: +{hdp}", style=discord.ButtonStyle.danger)
            btn_a.callback = lambda i, mid=m['id'], tn=a_name, c=1, h=hdp: i.response.send_modal(BettingModal(mid, tn, c, h))
            
            view.add_item(btn_h); view.add_item(btn_a)
            await channel.send(embed=embed, view=view)
    except: pass

# --- 💰 TỰ ĐỘNG TRẢ THƯỞNG ---
@tasks.loop(minutes=10)
async def auto_payout():
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers=headers).json()
        for m in res.get('matches', []):
            m_id = str(m['id'])
            conn = sqlite3.connect(DB_PATH)
            bets = conn.execute("SELECT id, user_id, amount, choice, hdp FROM bets WHERE match_id = ? AND status = 0", (m_id,)).fetchall()
            
            s_h, s_a = m['score']['fullTime']['home'], m['score']['fullTime']['away']
            for b_id, u_id, amt, choice, hdp in bets:
                win = (choice == 0 and (s_h - hdp) > s_a) or (choice == 1 and (s_h - hdp) < s_a)
                if win:
                    update_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(amt * 1.95), u_id))
                update_db("UPDATE bets SET status = 1 WHERE id = ?", (b_id,))
            conn.close()
    except: pass

# --- 🏆 BẢNG XẾP HẠNG ---
@tasks.loop(minutes=10)
async def auto_bxh():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    conn = sqlite3.connect(DB_PATH)
    top = conn.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10").fetchall()
    conn.close()
    
    embed = discord.Embed(title="🏆 TOP ĐẠI GIA SERVER", color=0xf1c40f, timestamp=datetime.utcnow())
    for i, (uid, c) in enumerate(top, 1):
        user = bot.get_user(uid)
        embed.add_field(name=f"#{i} {user.name if user else uid}", value=f"💰 `{c:,}` Coins", inline=False)
    
    await channel.purge(limit=1); await channel.send(embed=embed)

# --- 🛒 SHOP & TICKET ---
@bot.command()
async def mua(ctx, *, item_name: str):
    conn = sqlite3.connect(DB_PATH)
    item = conn.execute("SELECT price FROM shop WHERE item_name = ?", (item_name,)).fetchone()
    user = conn.execute("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,)).fetchone()
    
    if not item or (user[0] if user else 0) < item[0]:
        return await ctx.send("❌ Không đủ tiền hoặc vật phẩm không tồn tại!")

    update_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (item[0], ctx.author.id))
    
    overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
    ticket = await ctx.guild.create_text_channel(f"🎟️-{item_name}-{ctx.author.name}", overwrites=overwrites)
    await ticket.send(f"🛒 {ctx.author.mention} đã mua **{item_name}**. Chờ Admin xử lý!")
    await ctx.send(f"✅ Đã tạo ticket tại {ticket.mention}")

# --- QUẢN TRỊ ADMIN ---
@bot.command()
@is_admin()
async def nap(ctx, m: discord.Member, amt: int):
    update_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (m.id,))
    update_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, m.id))
    await ctx.send(f"✅ Đã nạp `{amt:,}` cho {m.mention}")

@bot.command()
async def vi(ctx):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,)).fetchone()
    await ctx.send(f"💳 Ví của bạn: **{res[0] if res else 0:,}** Coins")

@bot.event
async def on_ready():
    init_db()
    auto_update_matches.start()
    auto_payout.start()
    auto_bxh.start()
    print(f"🚀 {bot.user} IS READY!")

bot.run(TOKEN)
