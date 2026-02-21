import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import random
import os
import requests
import asyncio
from datetime import datetime, timedelta

# ================= CẤU HÌNH HỆ THỐNG =================
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ID_KENH_BONG_DA = 1474672512708247582 
ID_KENH_BXH = 1474674662792232981
ID_CATEGORY_TICKET = 1474672512708247582 
ADMIN_ROLES = [1465374336214106237, 1465376049452810306]
BIG_LEAGUES = ['PL', 'CL', 'BL1', 'SA', 'PD', 'FL1']
DB_PATH = 'economy.db'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================= DATABASE ENGINE (LOGIC KINH TẾ) =================
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = cur.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res else None) if one else res

# ================= HỆ THỐNG SHOP TICKET (PHÂN QUYỀN CHUẨN) =================
class TicketSystem(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🛒 MUA ACC / CÀY THUÊ", style=discord.ButtonStyle.primary, custom_id="buy_btn", emoji="💳")
    async def buy_callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        for r_id in ADMIN_ROLES:
            role = guild.get_role(r_id)
            if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        chan = await guild.create_text_channel(f"🛒-{interaction.user.name}", overwrites=overwrites, category=guild.get_channel(ID_CATEGORY_TICKET))
        
        embed = discord.Embed(title="🎫 TICKET HỖ TRỢ GIAO DỊCH", color=0x3498db, timestamp=datetime.now())
        embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.description = f"Chào {interaction.user.mention}!\n\n> Bạn vui lòng nhắn yêu cầu cày thuê hoặc mua Acc tại đây.\n> Admin <@&{ADMIN_ROLES[0]}> sẽ sớm có mặt.\n\n**Vui lòng không spam.**"
        
        msg = await chan.send(content=f"{interaction.user.mention} | Hỗ trợ viên", embed=embed)
        await msg.pin()
        await interaction.response.send_message(f"✅ Đã tạo kênh hỗ trợ: {chan.mention}", ephemeral=True)

# ================= MODAL CƯỢC BÓNG ĐÁ (XỬ LÝ TRỪ TIỀN) =================
class BetModal(ui.Modal, title='🎫 NHẬP SỐ TIỀN CƯỢC'):
    amount = ui.TextInput(label='Số xu muốn cược (Tối thiểu 100)', placeholder='Ví dụ: 5000', min_length=1, max_length=10)

    def __init__(self, match_id, team_name, hdp):
        super().__init__()
        self.match_id, self.team_name, self.hdp = match_id, team_name, hdp

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount.value)
            if val < 100: return await interaction.response.send_message("❌ Tiền cược tối thiểu là 100 xu!", ephemeral=True)
        except: return await interaction.response.send_message("❌ Vui lòng chỉ nhập số!", ephemeral=True)

        user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (interaction.user.id,), one=True)
        if not user_data or user_data[0] < val:
            return await interaction.response.send_message("❌ Bạn không đủ xu! Hãy nạp thêm hoặc chơi tài xỉu.", ephemeral=True)

        query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, interaction.user.id))
        query_db("INSERT INTO bets (user_id, match_id, amount, team, hdp) VALUES (?, ?, ?, ?, ?)", 
                 (interaction.user.id, self.match_id, val, self.team_name, self.hdp))
        
        await interaction.response.send_message(f"✅ Đã đặt cược **{val:,}** xu cho **{self.team_name}**!", ephemeral=True)

# ================= ⚽ TỰ ĐỘNG CẬP NHẬT BÓNG ĐÁ & GHIM TRẬN =================
@tasks.loop(minutes=5)
async def auto_football():
    channel = bot.get_channel(ID_KENH_BONG_DA)
    if not channel or not API_KEY: return
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])[:8]
        old_pins = await channel.pins()

        # Dọn dẹp tin nhắn bot không ghim
        await channel.purge(limit=20, check=lambda m: m.author == bot.user and not m.pinned)

        for m in matches:
            status = m['status']
            h_team, a_team = m['homeTeam'], m['awayTeam']
            h_score = m['score']['fullTime']['home'] if m['score']['fullTime']['home'] is not None else 0
            a_score = m['score']['fullTime']['away'] if m['score']['fullTime']['away'] is not None else 0
            
            # GIAO DIỆN HÌNH 3 (SẮP ĐÁ - LOGO 1:1)
            if status == 'SCHEDULED':
                hdp = random.choice([0, 0.25, 0.5, 0.75, 1.0])
                time_vn = (datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)).strftime("%H:%M")
                
                embed = discord.Embed(title=f"🏆 {m['competition']['name']}", color=0x2ecc71)
                embed.set_author(name=f"🏠 {h_team['name']}", icon_url=h_team.get('crest'))
                embed.set_thumbnail(url=a_team.get('crest')) # Logo đối xứng 1:1
                embed.description = (
                    f"### 🏟️ {h_team['name']} vs {a_team['name']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏰ **Giờ đá:** `{time_vn}`\n"
                    f"⚖️ **Kèo chấp:** Chủ chấp `{hdp}`\n"
                    f"💰 **Tỉ lệ:** 1 ăn 0.95 (Trừ phí sàn)\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                
                view = ui.View(timeout=None)
                btn_h = ui.Button(label=f"Cược {h_team['name']}", style=discord.ButtonStyle.success, emoji="🏟️")
                btn_a = ui.Button(label=f"Cược {a_team['name']}", style=discord.ButtonStyle.danger, emoji="✈️")
                
                btn_h.callback = lambda i, t=h_team['name'], mid=m['id'], h=hdp: i.response.send_modal(BetModal(mid, t, h))
                btn_a.callback = lambda i, t=a_team['name'], mid=m['id'], h=hdp: i.response.send_modal(BetModal(mid, t, -h))
                
                view.add_item(btn_h); view.add_item(btn_a)
                msg = await channel.send(embed=embed, view=view)
                
                if m['competition']['code'] in BIG_LEAGUES: await msg.pin()

            # GIAO DIỆN HÌNH 4 (ĐANG ĐÁ / KẾT THÚC)
            elif status in ['IN_PLAY', 'FINISHED']:
                color = 0xff0000 if status == 'IN_PLAY' else 0x7f8c8d
                title = "🔴 ĐANG THI ĐẤU" if status == 'IN_PLAY' else "🏁 KẾT THÚC"
                
                embed = discord.Embed(title=f"{m['competition']['name']} · {title}", color=color)
                embed.set_author(name=h_team['name'], icon_url=h_team.get('crest'))
                embed.set_thumbnail(url=a_team.get('crest'))
                embed.description = f"# {h_score}  —  {a_score}\n━━━━━━━━━━━━━━━━━━━━"
                
                await channel.send(embed=embed)
                
                if status == 'FINISHED': # Xóa ghim khi kết thúc
                    for pin in old_pins:
                        if pin.author == bot.user and h_team['name'] in pin.embeds[0].author.name:
                            await pin.unpin()
    except: pass

# ================= 🏆 BẢNG XẾP HẠNG & VÍ (LOGIC TÀI CHÍNH) =================
@tasks.loop(minutes=10)
async def update_leaderboard():
    channel = bot.get_channel(ID_KENH_BXH)
    if not channel: return
    top_users = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    
    embed = discord.Embed(title="🏆 BẢNG VINH DANH ĐẠI GIA", color=0xf1c40f, timestamp=datetime.now())
    embed.set_thumbnail(url="https://i.imgur.com/8E9S9zY.png")
    
    lb = ""
    for i, (uid, coins) in enumerate(top_users, 1):
        medal = ["🥇", "🥈", "🥉", "👤"][i-1] if i <= 3 else "👤"
        lb += f"{medal} **Top {i}** | <@{uid}>\n> 💰 Tài sản: `{coins:,}` xu\n"
    
    embed.description = lb if lb else "Chưa có dữ liệu."
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    coins = d[0] if d else 0
    embed = discord.Embed(title="💳 VÍ TIỀN DISCORD", color=0x2f3136)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.add_field(name="👤 Người dùng", value=ctx.author.mention, inline=True)
    embed.add_field(name="💰 Số dư", value=f"`{coins:,}` xu", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def nap(ctx, member: discord.Member, amount: int):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        query_db("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (member.id,))
        query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, member.id))
        await ctx.send(f"✅ Đã nạp **{amount:,}** xu cho {member.mention}")

# ================= 🎰 TÀI XỈU NẶN (KỊCH TÍNH) =================
@bot.command()
async def taixiu(ctx, choice: str, amt: int):
    choice = choice.lower()
    if choice not in ['tai', 'xiu']: return await ctx.send("❌ Cú pháp: `!taixiu [tai/xiu] [số tiền]`")
    
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not d or d[0] < amt: return await ctx.send("❌ Ví của bạn không đủ xu!")

    msg = await ctx.send(embed=discord.Embed(description="🎰 **Đang lắc bát... hãy chờ nặn!**", color=0xffff00))
    await asyncio.sleep(3) # Hiệu ứng nặn 3 giây

    dices = [random.randint(1, 6) for _ in range(3)]
    total = sum(dices)
    res = "tai" if total >= 11 else "xiu"
    win = (choice == res)
    
    reward = int(amt * 0.95) if win else -amt
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, ctx.author.id))
    
    embed = discord.Embed(title="🎰 KẾT QUẢ TÀI XỈU", color=0x2ecc71 if win else 0xe74c3c)
    embed.add_field(name="🎲 Xúc xắc", value=f"**{dices[0]} · {dices[1]} · {dices[2]}**", inline=True)
    embed.add_field(name="🎯 Tổng", value=f"**{total}** ({res.upper()})", inline=True)
    embed.description = f"### {'✨ THẮNG!' if win else '💀 THUA RỒI!'}\nBiến động: `{'+' if win else ''}{reward:,}` xu"
    await msg.edit(embed=embed)

# ================= SHOP MENU & KHỞI CHẠY =================
@bot.command()
async def setupshop(ctx):
    if any(r.id in ADMIN_ROLES for r in ctx.author.roles):
        embed = discord.Embed(title="🛒 SHOP GIAO DỊCH TỰ ĐỘNG", color=0x9b59b6)
        embed.description = "Nhấn nút dưới để liên hệ Admin mua Acc hoặc cày thuê."
        await ctx.send(embed=embed, view=TicketSystem())

@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, hdp REAL)')
    auto_football.start()
    update_leaderboard.start()
    bot.add_view(TicketSystem())
    print(f"🔥 {bot.user} Đã Online - Sẵn sàng phục vụ!")

bot.run(TOKEN)
