# ================= VERDICT MASTER 2.0 =================
import discord
from discord.ext import commands, tasks
from discord import ui
import sqlite3
import os
import requests
import random
from datetime import datetime, timezone, timedelta

TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('FOOTBALL_API_KEY')
ODDS_KEY = os.getenv('ODDS_API_KEY')

ID_KENH_CUOC = 1474793205299155135
ID_KENH_LIVE = 1474672512708247582
ALLOWED_LEAGUES = ['PL', 'PD', 'CL', 'BL1', 'SA']

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ================= DATABASE =================
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

# ================= TIME UTILS =================
def parse_utc(utc_str):
    return datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def vn_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone(timezone(timedelta(hours=7))).strftime('%H:%M - %d/%m')

# ================= FETCH ODDS =================
def fetch_odds_from_api(home_team_name):
    if not ODDS_KEY:
        return 0.5, 2.5, 1.95, 1.95, 1.90, 1.90

    url = "https://api.the-odds-api.com/v4/sports/soccer/odds"
    params = {
        'apiKey': ODDS_KEY,
        'regions': 'eu',
        'markets': 'spreads,totals',
        'oddsFormat': 'decimal'
    }

    try:
        res = requests.get(url, params=params).json()
        for data in res:
            if home_team_name.lower() in data['home_team'].lower():
                hcap, ou = 0.5, 2.5
                home_odds, away_odds = 1.95, 1.95
                over_odds, under_odds = 1.90, 1.90

                for bookie in data['bookmakers']:
                    for market in bookie['markets']:
                        if market['key'] == 'spreads':
                            hcap = market['outcomes'][0]['point']
                            home_odds = market['outcomes'][0]['price']
                            away_odds = market['outcomes'][1]['price']
                        if market['key'] == 'totals':
                            ou = market['outcomes'][0]['point']
                            over_odds = market['outcomes'][0]['price']
                            under_odds = market['outcomes'][1]['price']

                return hcap, ou, home_odds, away_odds, over_odds, under_odds

        return 0.5, 2.5, 1.95, 1.95, 1.90, 1.90
    except:
        return 0.5, 2.5, 1.95, 1.95, 1.90, 1.90

# ================= BET MODAL =================
class BetModal(ui.Modal, title='🎫 PHIẾU CƯỢC'):
    amt = ui.TextInput(label='Số tiền cược', placeholder='Tối thiểu 10,000...')

    def __init__(self, m_id, side, team, line, odds, type_bet):
        super().__init__()
        self.m_id = m_id
        self.side = side
        self.team = team
        self.line = line
        self.odds = odds
        self.type_bet = type_bet

    async def on_submit(self, i: discord.Interaction):
        try:
            val = int(self.amt.value)
            if val < 10000:
                return await i.response.send_message("❌ Cược tối thiểu 10,000!", ephemeral=True)

            u = query_db("SELECT coins FROM users WHERE user_id = ?", (i.user.id,), one=True)
            if not u or u['coins'] < val:
                return await i.response.send_message("❌ Không đủ tiền!", ephemeral=True)

            query_db("UPDATE users SET coins = coins - ? WHERE user_id = ?", (val, i.user.id))

            query_db("""
                INSERT INTO bets (user_id, match_id, side, amount, handicap, odds, status)
                VALUES (?,?,?,?,?,?,'PENDING')
            """, (i.user.id, self.m_id, self.side, val, self.line, self.odds))

            bet_id = query_db("SELECT last_insert_rowid() as id", one=True)['id']

            receipt = discord.Embed(title="🎫 VÉ CƯỢC", color=0x2ecc71)
            receipt.description = (
                f"🆔 Vé: #{bet_id}\n"
                f"🏟 Trận: #{self.m_id}\n"
                f"⚖️ Kèo: {self.line}\n"
                f"💰 Cược: {val:,}\n"
                f"💎 Odds: {self.odds}"
            )
            await i.user.send(embed=receipt)
            await i.response.send_message("✅ Đặt cược thành công!", ephemeral=True)

        except:
            await i.response.send_message("❌ Lỗi nhập tiền!", ephemeral=True)
            # ================= MATCH BUTTON VIEW =================
class MatchView(ui.View):
    def __init__(self, match_id, home, away, handicap, ou, h_odds, a_odds, o_odds, u_odds):
        super().__init__(timeout=None)
        self.match_id = match_id

        # Handicap buttons
        self.add_item(ui.Button(
            label=f"{home} {handicap} ({h_odds})",
            style=discord.ButtonStyle.primary,
            custom_id=f"bet_{match_id}_HOME_{handicap}_{h_odds}"
        ))
        self.add_item(ui.Button(
            label=f"{away} +{handicap} ({a_odds})",
            style=discord.ButtonStyle.primary,
            custom_id=f"bet_{match_id}_AWAY_{handicap}_{a_odds}"
        ))

        # Over/Under buttons
        self.add_item(ui.Button(
            label=f"Tài {ou} ({o_odds})",
            style=discord.ButtonStyle.success,
            custom_id=f"bet_{match_id}_OVER_{ou}_{o_odds}"
        ))
        self.add_item(ui.Button(
            label=f"Xỉu {ou} ({u_odds})",
            style=discord.ButtonStyle.danger,
            custom_id=f"bet_{match_id}_UNDER_{ou}_{u_odds}"
        ))

# ================= BUTTON LISTENER =================
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        if interaction.data['custom_id'].startswith("bet_"):
            parts = interaction.data['custom_id'].split("_")
            _, m_id, side, line, odds = parts
            await interaction.response.send_modal(
                BetModal(int(m_id), side, "", line, float(odds), "MATCH")
            )

# ================= FETCH MATCHES =================
def fetch_matches():
    headers = {"X-Auth-Token": API_KEY}
    res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()
    matches = []

    for m in res.get('matches', []):
        if m['competition']['code'] in ALLOWED_LEAGUES:
            matches.append(m)
    return matches

# ================= AUTO POST MATCHES =================
@tasks.loop(minutes=30)
async def auto_post_matches():
    ch = bot.get_channel(ID_KENH_CUOC)
    if not ch:
        return

    matches = fetch_matches()
    for m in matches:
        if m['status'] == "TIMED":
            m_id = m['id']
            home = m['homeTeam']['name']
            away = m['awayTeam']['name']
            time_vn = vn_time(m['utcDate'])

            hcap, ou, h_odds, a_odds, o_odds, u_odds = fetch_odds_from_api(home)

            embed = discord.Embed(
                title=f"⚽ {m['competition']['name']}",
                color=0x3498db
            )
            embed.description = (
                f"────────────────────\n"
                f"{home} vs {away}\n"
                f"⏰ {time_vn}\n"
                f"────────────────────\n"
                f"⚖️ Kèo chấp: {hcap}\n"
                f"🎯 T/X: {ou}"
            )

            view = MatchView(m_id, home, away, hcap, ou, h_odds, a_odds, o_odds, u_odds)
            await ch.send(embed=embed, view=view)

# ================= AUTO PAYOUT =================
@tasks.loop(minutes=5)
async def auto_payout():
    headers = {"X-Auth-Token": API_KEY}
    res = requests.get("https://api.football-data.org/v4/matches", headers=headers).json()

    for m in res.get('matches', []):
        if m['status'] == "FINISHED":
            m_id = m['id']
            home_score = m['score']['fullTime']['home']
            away_score = m['score']['fullTime']['away']

            bets = query_db("SELECT * FROM bets WHERE match_id = ? AND status='PENDING'", (m_id,))
            for b in bets:
                win = False

                if b['side'] == "HOME":
                    if home_score > away_score:
                        win = True
                elif b['side'] == "AWAY":
                    if away_score > home_score:
                        win = True
                elif b['side'] == "OVER":
                    if home_score + away_score > float(b['handicap']):
                        win = True
                elif b['side'] == "UNDER":
                    if home_score + away_score < float(b['handicap']):
                        win = True

                if win:
                    payout = int(b['amount'] * b['odds'])
                    query_db("UPDATE users SET coins = coins + ?, wins = wins + 1 WHERE user_id = ?",
                             (payout, b['user_id']))
                    query_db("UPDATE bets SET status='WIN' WHERE id=?", (b['id'],))
                else:
                    query_db("UPDATE users SET losses = losses + 1 WHERE user_id = ?",
                             (b['user_id'],))
                    query_db("UPDATE bets SET status='LOSE' WHERE id=?", (b['id'],))

# ================= WALLET =================
@bot.command()
async def vi(ctx):
    u = query_db("SELECT * FROM users WHERE user_id=?", (ctx.author.id,), one=True)
    if not u:
        query_db("INSERT INTO users(user_id, coins, wins, losses) VALUES (?,?,?,?)",
                 (ctx.author.id, 100000, 0, 0))
        u = query_db("SELECT * FROM users WHERE user_id=?", (ctx.author.id,), one=True)

    total = u['wins'] + u['losses']
    winrate = (u['wins'] / total * 100) if total > 0 else 0

    embed = discord.Embed(title="💰 Ví của bạn", color=0xf1c40f)
    embed.description = (
        f"💵 Tiền: {u['coins']:,}\n"
        f"🏆 Thắng: {u['wins']}\n"
        f"💀 Thua: {u['losses']}\n"
        f"📊 Winrate: {winrate:.2f}%"
    )
    await ctx.send(embed=embed)

# ================= LEADERBOARD =================
@bot.command()
async def top(ctx):
    users = query_db("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    embed = discord.Embed(title="🏆 TOP 10 ĐẠI GIA", color=0xe67e22)

    desc = ""
    for i, u in enumerate(users, 1):
        user = bot.get_user(u['user_id'])
        desc += f"{i}. {user} - {u['coins']:,}\n"

    embed.description = desc
    await ctx.send(embed=embed)

# ================= HISTORY =================
@bot.command()
async def lichsu(ctx):
    bets = query_db("SELECT * FROM bets WHERE user_id=? ORDER BY id DESC LIMIT 10", (ctx.author.id,))
    embed = discord.Embed(title="📜 Lịch sử cược", color=0x9b59b6)

    desc = ""
    for b in bets:
        desc += f"#{b['id']} | {b['side']} | {b['amount']:,} | {b['status']}\n"

    embed.description = desc or "Chưa có cược."
    await ctx.send(embed=embed)

# ================= MINI GAME =================
@bot.command()
async def taixiu(ctx, amount: int, choice: str):
    if amount < 10000:
        return await ctx.send("❌ Tối thiểu 10,000")

    u = query_db("SELECT * FROM users WHERE user_id=?", (ctx.author.id,), one=True)
    if not u or u['coins'] < amount:
        return await ctx.send("❌ Không đủ tiền")

    dice = random.randint(1, 6) + random.randint(1, 6)
    result = "tai" if dice >= 7 else "xiu"

    query_db("UPDATE users SET coins = coins - ? WHERE user_id=?", (amount, ctx.author.id))

    if choice.lower() == result:
        win = int(amount * 1.9)
        query_db("UPDATE users SET coins = coins + ?, wins = wins + 1 WHERE user_id=?",
                 (win, ctx.author.id))
        await ctx.send(f"🎲 Ra {dice} → Bạn thắng {win:,}")
    else:
        query_db("UPDATE users SET losses = losses + 1 WHERE user_id=?", (ctx.author.id,))
        await ctx.send(f"🎲 Ra {dice} → Bạn thua!")

# ================= ON READY =================
@bot.event
async def on_ready():
    print(f"🔥 Bot đã online: {bot.user}")
    auto_post_matches.start()
    auto_payout.start()

# ================= RUN =================
bot.run(TOKEN)
