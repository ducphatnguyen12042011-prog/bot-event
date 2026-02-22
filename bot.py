import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta
const { connectDB, Economy } = require('./database'); // Gọi file database.js cùng thư mục

// 1. Kết nối đến "túi tiền chung" trên Railway
connectDB(process.env.MONGO_URL);

// 2. Ví dụ: Khi có người dùng gõ lệnh "!money"
// Bạn chỉ cần gọi:
const balance = await Economy.getBalance(message.author.id);
message.reply(`Ví của bạn đang có: ${balance} VNĐ`);

# --- 1. CẤU HÌNH ---
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ODDS_KEY = os.getenv('ODDS_API_KEY') 
ID_KENH_CUOC = 1474793205299155135
ID_KENH_LIVE = 1474672512708247582
ALLOWED_LEAGUES = ['PL', 'PD', 'CL', 'BL1', 'SA']

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- 2. DATABASE ---
def query_db(sql, params=(), one=False):
    conn = sqlite3.connect('verdict_master.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.commit()
        return (res[0] if res and one else res)
    finally:
        conn.close()

# --- 3. HELPER ---
def vn_now():
    return datetime.now(timezone(timedelta(hours=7)))

def vn_time(utc_str):
    dt = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

# --- 4. TỰ ĐỘNG CẬP NHẬT VÉ TRONG DM & TRẢ THƯỞNG ---
@tasks.loop(minutes=5)
async def auto_payout():
    headers = {"X-Auth-Token": API_KEY}
    try:
        response = requests.get("https://api.football-data.org/v4/matches?status=FINISHED", headers=headers)
        data = response.json()
        for match in data.get('matches', []):
            m_id = match['id']
            bets = query_db("SELECT * FROM bets WHERE match_id = ? AND status = 'PENDING'", (m_id,))
            if not bets: continue

            h_score = match['score']['fullTime']['home']
            a_score = match['score']['fullTime']['away']
            total = h_score + a_score

            for b in bets:
                won, draw_refund = False, False
                if b['side'] == 'hoa':
                    if h_score == a_score: won = True
                elif b['side'] == 'chu':
                    if (h_score - a_score) + b['handicap'] > 0: won = True
                    elif (h_score - a_score) + b['handicap'] == 0: draw_refund = True
                elif b['side'] == 'khach':
                    if (a_score - h_score) + b['handicap'] > 0: won = True
                    elif (a_score - h_score) + b['handicap'] == 0: draw_refund = True
                elif b['side'] == 'tai':
                    if total > b['handicap']: won = True
                    elif total == b['handicap']: draw_refund = True
                elif b['side'] == 'xiu':
                    if total < b['handicap']: won = True
                    elif total == b['handicap']: draw_refund = True

                status_res, payout, color = 'LOST', 0, 0xe74c3c
                if won:
                    rate = 3.0 if b['side'] == 'hoa' else 1.95
                    payout = int(b['amount'] * rate)
                    query_db("UPDATE users SET coins = coins + ?, win_amt = win_amt + ? WHERE user_id = ?", (payout, payout - b['amount'], b['user_id']))
                    status_res, color = 'WON', 0x2ecc71
                elif draw_refund:
                    payout = b['amount']
                    query_db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (payout, b['user_id']))
                    status_res, color = 'DRAW', 0x95a5a6
                else:
                    query_db("UPDATE users SET lose_amt = lose_amt + ? WHERE user_id = ?", (b['amount'], b['user_id']))
                
                query_db("UPDATE bets SET status = ? WHERE id = ?", (status_res, b['id']))

                # SỬA VÉ TRONG DM KHI CÓ KẾT QUẢ
                try:
                    if b['msg_id']:
                        user = await bot.fetch_user(b['user_id'])
                        msg = await user.fetch_message(b['msg_id'])
                        
                        new_emb = msg.embeds[0]
                        status_text = "THẮNG 🎉" if won else ("HÒA 🤝" if draw_refund else "THUA 💀")
                        new_emb.title = f"🏁 KẾT QUẢ GIAO DỊCH: {status_text}"
                        new_emb.color = color
                        new_emb.clear_fields()
                        new_emb.add_field(name="📌 Mã Trận", value=f"`#{m_id}`", inline=True)
                        new_emb.add_field(name="⚽ Tỉ số", value=f"**{h_score} - {a_score}**", inline=True)
                        new_emb.add_field(name="💰 Tiền nhận", value=f"**{payout:,}** Cash", inline=True)
                        new_emb.set_footer(text=f"Hoàn tất: {vn_now().strftime('%H:%M - %d/%m')}")
                        await msg.edit(embed=new_emb)
                except: pass
    except Exception as e: print(f"Lỗi payout: {e}")

# --- 5. GIAO DIỆN PHIẾU CƯỢC (MODAL) ---
class BetModal(ui.Modal, title='🎫 XÁC NHẬN VÉ CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược (Min: 10,000)', placeholder='Nhập số tiền...', min_length=5)
    
    def __init__(self, m_id, side, team, line, type_bet):
        super().__init__()
        self.m_id, self.side, self.team, self.line, self.type_bet = m_id, side, team, line, type_bet

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val: return await i.response.send_message("❌ Ví không đủ tiền!", ephemeral=True)

            line_txt = f"Chấp {self.line:+0.2g}" if self.type_bet == 'hcap' else (f"{'TÀI' if self.side == 'tai' else 'XỈU'} {self.line}" if self.type_bet == 'ou' else "Kèo 1x2")

            # GỬI VÉ CỰC ĐẸP VÀO DM
            receipt = discord.Embed(title="🎫 VÉ CƯỢC ĐÃ ĐƯỢC GHI NHẬN", color=0x3498db)
            receipt.set_author(name=i.user.name, icon_url=i.user.display_avatar.url)
            receipt.add_field(name="💎 Lựa chọn", value=f"**{self.team}**", inline=True)
            receipt.add_field(name="⚖️ Kèo", value=f"`{line_txt}`", inline=True)
            receipt.add_field(name="💰 Tiền cược", value=f"**{val:,}** Cash", inline=False)
            receipt.add_field(name="⏳ Trạng thái", value="`🟡 Đang chờ kết quả...`", inline=True)
            receipt.set_footer(text=f"ID Giao dịch: {random.randint(100000, 999999)}")
            receipt.timestamp = datetime.now()
            
            dm_msg = await i.user.send(embed=receipt)

            query_db("UPDATE users SET coins = coins - ?, spent_amt = spent_amt + ? WHERE user_id = ?", (val, val, i.user.id))
            query_db("INSERT INTO bets (user_id, match_id, side, amount, handicap, status, msg_id) VALUES (?,?,?,?,?,?,?)", 
                     (i.user.id, self.m_id, self.side, val, self.line, 'PENDING', dm_msg.id))

            await i.response.send_message(f"✅ Đã đặt cược thành công! Kiểm tra DM để xem vé.", ephemeral=True)
        except:
            await i.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

# --- 6. GIAO DIỆN NÚT BẤM TRẬN ĐẤU ---
class MatchControlView(ui.View):
    def __init__(self, m, hcap, ou):
        super().__init__(timeout=None)
        self.m, self.hcap, self.ou = m, hcap, ou

    @ui.button(label="🏠 Chủ", style=discord.ButtonStyle.primary)
    async def c1(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "chu", self.m['homeTeam']['shortName'], self.hcap, 'hcap'))

    @ui.button(label="🤝 Hòa", style=discord.ButtonStyle.secondary)
    async def c_draw(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "hoa", "Hòa (1x2)", 0, '1x2'))

    @ui.button(label="✈️ Khách", style=discord.ButtonStyle.danger)
    async def c2(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "khach", self.m['awayTeam']['shortName'], -self.hcap, 'hcap'))

    @ui.button(label="🔥 Tài", style=discord.ButtonStyle.success, row=1)
    async def c3(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "tai", "Tài", self.ou, 'ou'))

    @ui.button(label="❄️ Xỉu", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, i, b): await i.response.send_modal(BetModal(self.m['id'], "xiu", "Xỉu", self.ou, 'ou'))

# --- 7. TỰ ĐỘNG CẬP NHẬT SCOREBOARD & LIVE ---
@tasks.loop(minutes=2)
async def update_scoreboard():
    ch_cuoc = bot.get_channel(ID_KENH_CUOC)
    ch_live = bot.get_channel(ID_KENH_LIVE)
    if not ch_cuoc: return
    
    now_utc = datetime.now(timezone.utc)
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
        matches = res.get('matches', [])
        
        # --- CẬP NHẬT KÈO (KÊNH CƯỢC) ---
        await ch_cuoc.purge(limit=15, check=lambda m: m.author == bot.user)
        upcoming = [x for x in matches if x['status'] == 'TIMED' and x['competition']['code'] in ALLOWED_LEAGUES][:8]
        
        for m in upcoming:
            m_id = m['id']
            match_time = parse_utc(m['utcDate'])
            is_locked = now_utc >= (match_time - timedelta(minutes=5))
            
            saved = query_db("SELECT hcap, ou FROM match_odds WHERE match_id = ?", (m_id,), one=True)
            if saved: hcap, ou = saved['hcap'], saved['ou']
            else:
                hcap, ou = 0.5, 2.5 # Mặc định hoặc gọi hàm lấy kèo của bạn
                query_db("INSERT INTO match_odds (match_id, hcap, ou) VALUES (?, ?, ?)", (m_id, hcap, ou))

            emb = discord.Embed(title=f"🏟️ {m['competition']['name'].upper()}", color=0x3498db if not is_locked else 0x95a5a6)
            emb.add_field(name="⚽ TRẬN ĐẤU", value=f"🏠 **{m['homeTeam']['name']}**\n✈️ **{m['awayTeam']['name']}**", inline=True)
            emb.add_field(name="📊 KÈO CHẤP", value=f"`{hcap:+0.2g}`", inline=True)
            emb.add_field(name="🕒 THỜI GIAN", value=f"`{vn_time(m['utcDate'])}`", inline=True)
            emb.description = f"🔥 **Tài Xỉu:** `{ou}` | ⚖️ **Trạng thái:** {'✅ MỞ' if not is_locked else '🔒 ĐÓNG'}"
            emb.set_thumbnail(url=m['competition']['emblem'])
            
            if not is_locked: await ch_cuoc.send(embed=emb, view=MatchControlView(m, hcap, ou))
            else: await ch_cuoc.send(embed=emb)

        # --- CẬP NHẬT LIVE (KÊNH LIVE) ---
        if ch_live:
            await ch_live.purge(limit=10, check=lambda m: m.author == bot.user)
            lives = [x for x in matches if x['status'] in ['IN_PLAY', 'LIVE', 'PAUSED']]
            if not lives:
                await ch_live.send("✨ Hiện không có trận đấu nào đang diễn ra.")
            for m in lives:
                s = m['score']['fullTime']
                emb_l = discord.Embed(title=f"🔴 LIVE: {m['competition']['name']}", color=0xe74c3c)
                emb_l.description = f"🏟️ **{m['homeTeam']['name']}** ` {s['home']} - {s['away']} `  **{m['awayTeam']['name']}**"
                emb_l.set_footer(text="Dữ liệu cập nhật tự động mỗi 2 phút")
                await ch_live.send(embed=emb_l)

    except Exception as e: print(f"Lỗi scoreboard: {e}")

# --- 8. LỆNH BOT ---
@bot.command()
async def vi(ctx):
    u = query_db("SELECT * FROM users WHERE user_id = ?", (ctx.author.id,), one=True)
    if not u: return await ctx.send("💳 Hãy đặt cược để khởi tạo ví!")
    emb = discord.Embed(title=f"💳 VÍ CỦA {ctx.author.name}", color=0x2ecc71)
    emb.add_field(name="💰 Số dư", value=f"**{u['coins']:,}** Cash", inline=False)
    emb.add_field(name="📈 Lợi nhuận", value=f"{u['win_amt'] - u['lose_amt']:+,} Cash", inline=True)
    emb.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=emb)

@bot.command()
@commands.has_permissions(administrator=True)
async def nap(ctx, user: discord.Member, amt: int):
    query_db("INSERT INTO users (user_id, coins) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET coins = coins + ?", (user.id, amt, amt))
    await ctx.send(f"✅ Đã nạp `{amt:,}` Cash cho {user.mention}")

# --- 9. KHỞI CHẠY ---
@bot.event
async def on_ready():
    query_db('CREATE TABLE IF NOT EXISTS match_odds (match_id INTEGER PRIMARY KEY, hcap REAL, ou REAL)')
    query_db('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 10000, spent_amt INTEGER DEFAULT 0, win_amt INTEGER DEFAULT 0, lose_amt INTEGER DEFAULT 0)')
    query_db('CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id INTEGER, side TEXT, amount INTEGER, handicap REAL, status TEXT, msg_id INTEGER)')
    
    try: query_db("ALTER TABLE bets ADD COLUMN msg_id INTEGER")
    except: pass

    update_scoreboard.start()
    auto_payout.start()
    print(f"🚀 {bot.user.name} Sẵn sàng!")

bot.run(TOKEN)
