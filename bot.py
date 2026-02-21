import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ADMIN_ROLE_ID = 1465374336214106237 
ID_BXH = 1474674662792232981        
ID_BONG_DA = 1474672512708247582    

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
current_matches = {}

# --- UI: VÍ & NÚT LỊCH SỬ ---
class WalletView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.button(label="📜 Lịch sử cược", style=discord.ButtonStyle.grey)
    async def history(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Đây không phải ví của bạn!", ephemeral=True)
        history = query_db("SELECT team, amount, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (self.user_id,))
        if not history:
            return await interaction.response.send_message("📭 Chưa có giao dịch nào.", ephemeral=True)
        embed = discord.Embed(title="📜 LỊCH SỬ GIAO DỊCH", color=0x3498db)
        desc = "".join([f"{'✅' if 'WIN' in s else ('⏳' if 'PENDING' in s else '❌')} **{t}** | `{a:,}` | {s}\n" for t, a, s in history])
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- 1. GIAO DIỆN TỈ SỐ & LOGO ĐỐI XỨNG ---
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
            h_name = m['homeTeam']['shortName'] or m['homeTeam']['name']
            a_name = m['awayTeam']['shortName'] or m['awayTeam']['name']
            h_icon, a_icon = m['homeTeam'].get('crest'), m['awayTeam'].get('crest')
            h_score, a_score = m['score']['fullTime']['home'] or 0, m['score']['fullTime']['away'] or 0
            start_time = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

            embed = discord.Embed(title="🏆 TRẬN ĐẤU ĐANG DIỄN RA 🏆", color=0x2b2d31)
            embed.set_author(name=f"{h_name}", icon_url=h_icon)
            embed.set_thumbnail(url=a_icon)
            
            score_box = f"{h_name}  ` {h_score} — {a_score} `  {a_name}"
            embed.add_field(name="📊 TỈ SỐ HIỆN TẠI", value=f"```py\n{score_box}\n```", inline=False)
            embed.add_field(name="🏠 CHỦ NHÀ", value=f"**{h_name}**\nKèo: `- 0.5`", inline=True)
            embed.add_field(name="✈️ SÂN KHÁCH", value=f"**{a_name}**\nKèo: `+ 0.5`", inline=True)
            embed.add_field(name="📅 CHI TIẾT", value=f"⏰ Bắt đầu: <t:{int(start_time.timestamp())}:R>\n🆔 Mã trận: `{mid}`", inline=False)
            embed.set_footer(text="Đóng cược 15 phút trước giờ đá")
            await channel.send(embed=embed)
    except: pass

# --- 2. LOGIC TRẢ THƯỞNG TỰ ĐỘNG ---
@tasks.loop(minutes=20)
async def auto_payout():
    pending_bets = query_db("SELECT id, user_id, match_id, amount, team FROM bets WHERE status = 'PENDING' AND match_id != 'TAI_XIU'")
    if not pending_bets: return

    try:
        res = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers={"X-Auth-Token": API_KEY}).json()
        finished_matches = {str(m['id']): m for m in res.get('matches', [])}

        for b_id, u_id, m_id, amt, t_bet in pending_bets:
            if m_id in finished_matches:
                m = finished_matches[m_id]
                h_name = m['homeTeam']['name']
                a_name = m['awayTeam']['name']
                h_score = m['score']['fullTime']['home']
                a_score = m['score']['fullTime']['away']

                # Xác định đội thắng thực tế (kèo chấp 0.5)
                winner = h_name if h_score > a_score else (a_name if a_score > h_score else "DRAW")
                
                is_win = (t_bet == winner)
                status = "WIN" if is_win else "LOSE"
                
                if is_win:
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amt * 2, u_id))
                
                query_db("UPDATE bets SET status = ? WHERE id = ?", (status, b_id))
                
                # Thông báo cho người chơi
                try:
                    user = await bot.fetch_user(u_id)
                    result_msg = f"✅ Bạn đã THẮNG `{amt*2:,}` Cash từ trận {h_name} vs {a_name}!" if is_win else f"❌ Bạn đã THUA trận {h_name} vs {a_name}."
                    await user.send(result_msg)
                except: pass
    except: pass

# --- 3. ĐẶT CƯỢC & TÀI XỈU 60% ---
@bot.command()
async def cuoc(ctx, match_id: str, side: str, amount: int):
    if match_id not in current_matches: return await ctx.send("❌ Trận đấu không khả dụng!")
    match = current_matches[match_id]
    start_time = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    
    if datetime.now(timezone.utc) > (start_time - timedelta(minutes=15)):
        return await ctx.send("🚫 Đã quá giờ đặt cược!")

    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Không đủ tiền!")

    team_bet = match['homeTeam']['name'] if side.lower() in ["chu", "home"] else match['awayTeam']['name']
    query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, ctx.author.id))
    query_db("INSERT INTO bets (user_id, match_id, amount, team, status) VALUES (?, ?, ?, ?, 'PENDING')", (ctx.author.id, match_id, amount, team_bet))
    await ctx.send("✅ Đã nhận kèo! Check DM nhận vé.")

@bot.command()
async def taixiu(ctx, side: str, amount: int):
    global history_cau
    side = side.lower()
    user_data = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not user_data or user_data[0] < amount: return await ctx.send("❌ Không đủ tiền!")

    is_rigged = random.randint(1, 100) <= 60
    total = random.randint(3, 18)
    res_text = "tai" if total >= 11 else "xiu"

    if is_rigged and res_text == side:
        total = random.randint(3, 10) if side == "tai" else random.randint(11, 18)
        res_text = "xiu" if total <= 10 else "tai"

    history_cau.append({"res": "T" if res_text == "tai" else "X", "val": total})
    win = (side == res_text)
    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount if win else -amount, ctx.author.id))
    await ctx.send(f"🎲 Kết quả: **{res_text.upper()}** ({total}). Bạn {'Thắng' if win else 'Thua'}")

@bot.command()
async def cau(ctx):
    if not history_cau: return await ctx.send("📑 Chưa có dữ liệu.")
    graph = "".join([f"{lvl:02d} ┃" + "".join([" ● " if e['val'] == lvl else "   " for e in history_cau[-15:]]) + "\n" for lvl in range(18, 0, -1)])
    embed = discord.Embed(title="📈 SOI CẦU TÀI XỈU (1-18)", description=f"```\n{graph}```", color=0xffd700)
    await ctx.send(embed=embed)

# --- 4. BXH & VÍ & SHOP ---
@tasks.loop(minutes=2)
async def update_leaderboard():
    channel = bot.get_channel(ID_BXH)
    if not channel: return
    top = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="✨ BẢNG XẾP HẠNG ĐẠI GIA VERDICT CASH ✨", color=0xf1c40f)
    desc = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + "".join([f"🔹 **Top {i+1}** | <@{u}>: `{c:,}`\n" for i, (u, c) in enumerate(top)])
    embed.description = desc
    await channel.purge(limit=5, check=lambda m: m.author == bot.user)
    await channel.send(embed=embed)

@bot.command()
async def vi(ctx):
    d = query_db("SELECT coins FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    embed = discord.Embed(title="💳 VÍ VERDICT CASH", description=f"Số dư: **{d[0] if d else 0:,}** Cash", color=0x2ecc71)
    await ctx.send(embed=embed, view=WalletView(ctx.author.id))

@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🛒 SHOP VẬT PHẨM", color=0x9b59b6)
    embed.add_field(name="1. Role [Đại Gia]", value="Giá: `5M Cash`", inline=False)
    await ctx.send(embed=embed)

# --- KHỞI CHẠY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, amount INTEGER, team TEXT, status TEXT)')
    auto_update_matches.start()
    update_leaderboard.start()
    auto_payout.start()
    print("🚀 Bot Full Tự Động đã sẵn sàng!")

bot.run(TOKEN)
