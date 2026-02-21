import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime, timedelta

# --- CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]
DB_PATH = '/app/economy.db'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- DATABASE CHỐNG GIAN LẬN ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# --- CHỐNG SPAM ---
user_cooldowns = {}
def is_spamming(user_id, seconds=3):
    now = datetime.now()
    if user_id in user_cooldowns and now < user_cooldowns[user_id] + timedelta(seconds=seconds):
        return True
    user_cooldowns[user_id] = now
    return False

# --- MODAL CƯỢC BÓNG ĐÁ ---
class BettingModal(ui.Modal, title='🎫 XÁC NHẬN VÀO KÈO'):
    bet_input = ui.TextInput(label='Tiền cược (Số nguyên dương)', placeholder='Tối thiểu 100', min_length=1)

    def __init__(self, match_id, team_name, choice, hdp):
        super().__init__()
        self.match_id, self.team_name, self.choice, self.hdp = match_id, team_name, choice, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.bet_input.value.strip())
            if amt < 100: raise ValueError
        except:
            return await interaction.response.send_message("❌ Tiền cược không hợp lệ!", ephemeral=True)

        user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        balance = user_data[0] if user_data else 0
        
        if balance < amt:
            return await interaction.response.send_message("❌ Bạn không đủ tiền!", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, interaction.user.id))
        query_db("INSERT INTO bets (match_id, user_id, amount, choice, hdp) VALUES (?, ?, ?, ?, ?)", 
                 (self.match_id, interaction.user.id, amt, self.choice, self.hdp))
        
        await interaction.response.send_message(f"✅ Đã cược **{amt:,}** vào **{self.team_name}**!", ephemeral=True)

# --- ⚽ BÓNG ĐÁ: LOGO TO + NÚT BẤM ---
@tasks.loop(minutes=10)
async def auto_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=SCHEDULED", headers=headers).json()
        matches = res.get('matches', [])[:5]
        await channel.purge(limit=15, check=lambda m: m.author == bot.user)
        
        for m in matches:
            h_team, a_team = m['homeTeam'], m['awayTeam']
            hdp = random.choice([0, 0.25, 0.5, 0.75, 1.0])
            
            embed = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x00ffcc)
            embed.description = f"🏟️ **{h_team['name']}** vs **{a_team['name']}**\n⚖️ Kèo: Đội nhà chấp `{hdp}`"
            
            # 🖼️ LÀM ẢNH LOGO TO (Dùng set_image)
            if h_team.get('crest'):
                embed.set_image(url=h_team['crest'])
            if a_team.get('crest'):
                embed.set_thumbnail(url=a_team['crest'])

            view = ui.View(timeout=None)
            btn_h = ui.Button(label=f"Cược {h_team['name']}: -{hdp}", style=discord.ButtonStyle.success)
            btn_h.callback = lambda i, mid=m['id'], tn=h_team['name'], c=0, h=hdp: i.response.send_modal(BettingModal(mid, tn, c, h))
            
            btn_a = ui.Button(label=f"Cược {a_team['name']}: +{hdp}", style=discord.ButtonStyle.danger)
            btn_a.callback = lambda i, mid=m['id'], tn=a_team['name'], c=1, h=hdp: i.response.send_modal(BettingModal(mid, tn, c, h))
            
            view.add_item(btn_h); view.add_item(btn_a)
            await channel.send(embed=embed, view=view)
    except: pass

# --- 🎲 TÀI XỈU HIỆU ỨNG "NẶNG" ---
@bot.command()
async def taixiu(ctx, lua_chon: str, cuoc: str):
    if is_spamming(ctx.author.id): return await ctx.send("🕒 Đừng lắc quá nhanh, gãy tay đấy!")
    
    lua_chon = lua_chon.lower()
    if lua_chon not in ['tai', 'xiu']: return
    try:
        amt = int(cuoc)
        if amt < 100: raise ValueError
    except: return await ctx.send("❌ Tiền cược không hợp lệ!")

    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amt: return await ctx.send("❌ Bạn không đủ xu!")

    # Hiệu ứng nặn
    msg = await ctx.send(embed=discord.Embed(title="🎲 ĐANG NẶN...", color=0xffff00))
    await asyncio.sleep(3)

    dices = [random.randint(1, 6) for _ in range(3)]
    tong = sum(dices)
    res = "tai" if tong >= 11 else "xiu"
    win = (lua_chon == res)
    is_jackpot = (dices[0] == dices[1] == dices[2])

    if win:
        payout = int(amt * (3 if is_jackpot else 1.95))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (payout - amt, ctx.author.id))
    else:
        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amt, ctx.author.id))

    dice_map = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    embed = discord.Embed(title="🎰 KẾT QUẢ", color=0x2ecc71 if win else 0xe74c3c)
    embed.description = f"🎲 **{' '.join([dice_map[d] for d in dices])}**\n✨ Tổng: **{tong}** ({res.upper()})"
    if is_jackpot: embed.add_field(name="🔥 JACKPOT", value="X3 TIỀN THƯỞNG!")
    await msg.edit(embed=embed)

# --- 🛒 SHOP & TICKET ---
@bot.command()
async def shop(ctx):
    items = query_db("SELECT item_name, price FROM shop")
    embed = discord.Embed(title="🛒 CỬA HÀNG", color=0x9b59b6)
    for name, price in items:
        embed.add_field(name=f"📦 {name}", value=f"💰 `{price:,}` Coins", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def mua(ctx, *, item_name: str):
    item = query_db("SELECT price FROM shop WHERE item_name = ?", (item_name,), one=True)
    user = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not item or (user[0] if user else 0) < item[0]: return await ctx.send("❌ Lỗi mua hàng!")

    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (item[0], ctx.author.id))
    overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
    ticket = await ctx.guild.create_text_channel(f"🎟️-{item_name}-{ctx.author.name}", overwrites=overwrites)
    await ticket.send(f"🛒 {ctx.author.mention} đã mua **{item_name}**. Chờ Admin xử lý!")
    await ctx.send(f"✅ Ticket đã tạo: {ticket.mention}")

# --- ⚙️ HỆ THỐNG TRẢ THƯỞNG TỰ ĐỘNG ---
@tasks.loop(minutes=15)
async def auto_payout():
    headers = {"X-Auth-Token": API_KEY}
    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers=headers).json()
        for m in res.get('matches', []):
            m_id = str(m['id'])
            bets = query_db("SELECT id, user_id, amount, choice, hdp FROM bets WHERE match_id = ? AND status = 0", (m_id,))
            s_h, s_a = m['score']['fullTime']['home'], m['score']['fullTime']['away']
            for b_id, u_id, amt, choice, hdp in bets:
                win = (choice == 0 and (s_h - hdp) > s_a) or (choice == 1 and (s_h - hdp) < s_a)
                if win: query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (int(amt * 1.95), u_id))
                query_db("UPDATE bets SET status = 1 WHERE id = ?", (b_id,))
    except: pass

# --- ADMIN COMMANDS ---
@bot.command()
async def nap(ctx, m: discord.Member, amt: int):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (m.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt, m.id))
        await ctx.send(f"✅ Đã nạp `{amt:,}` cho {m.mention}")

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS shop (item_name TEXT PRIMARY KEY, price INTEGER)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, user_id INTEGER, amount INTEGER, choice INTEGER, hdp REAL, status INTEGER DEFAULT 0)')
    auto_football.start(); auto_payout.start()
    print(f"🚀 {bot.user} ONLINE!")

bot.run(TOKEN)
