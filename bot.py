import discord
from discord.ext import commands, tasks
import re
import json
import os
from datetime import datetime, timedelta
import pytz
import asyncio
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp

# ============================================================
#                    CONFIGURATION
# ============================================================
TOKEN = os.environ.get("DISCORD_TOKEN")
SERVER_ID = 1500881560067641396

# Channel IDs
REGISTRATION_CHANNEL_ID = 1501156569713348609   # Tag check channel
CATEGORY_ID             = 1501157421610041395   # Auto lock/unlock category
LEADERBOARD_CHANNEL_ID  = 1501157176482336848   # Weekly leaderboard
RESULT_SUBMIT_CHANNEL_ID= 1502270253785157712   # Match result submit
T2_QUALIFY_CHANNEL_ID   = 1501883016371241041   # T2 qualified players channel

# Role name (ID will be fetched automatically)
T2_QUALIFY_ROLE_NAME = "T2 QUALIFY 🏆"

# Tournament settings
MAX_TEAMS_PER_SLOT   = 25
REGISTRATION_HOUR    = 14   # 2:00 PM IST unlock
ANNOUNCE_HOUR        = 16   # 4:00 PM IST result message
IST                  = pytz.timezone("Asia/Kolkata")

# ============================================================
#                    BOT SETUP
# ============================================================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================================
#                    DATA STORAGE (JSON files)
# ============================================================
DATA_FILE    = "tournament_data.json"
RESULTS_FILE = "match_results.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"registered_teams": {}, "slot_teams": [], "plots": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    return {"weekly_results": {}, "team_stats": {}}

def save_results(data):
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ============================================================
#                    HELPER: FORMAT CHECK
# ============================================================
def check_registration_format(content):
    """
    Expected format:
    Team name - ....
    Team players name -
    @player discord ID tag  (x4)
    """
    lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
    if len(lines) < 6:
        return False, "❌ Format galat hai! Kam se kam 6 lines honi chahiye."

    if not lines[0].lower().startswith("team name"):
        return False, "❌ Pehli line 'Team name -' se shuru honi chahiye."

    if not lines[1].lower().startswith("team players name"):
        return False, "❌ Doosri line 'Team players name -' honi chahiye."

    player_lines = lines[2:]
    if len(player_lines) < 4:
        return False, f"❌ 4 players ke mention chahiye, sirf {len(player_lines)} hain."

    mention_pattern = re.compile(r"<@!?\d+>")
    for i, pl in enumerate(player_lines[:4]):
        if not mention_pattern.search(pl):
            return False, f"❌ Player {i+1} ka Discord tag (@mention) nahi mila."

    team_name = lines[0].split("-", 1)[-1].strip()
    if not team_name:
        return False, "❌ Team ka naam missing hai."

    players = [mention_pattern.findall(pl) for pl in player_lines[:4]]
    return True, {"team_name": team_name, "players": [p[0] for p in players]}

# ============================================================
#                    EVENT: ON READY
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ RKM Bot online! Logged in as {bot.user}")
    auto_lock_unlock.start()
    weekly_leaderboard.start()
    daily_slot_announce.start()

# ============================================================
#   FUNCTION 1: TAG FORMAT CHECK (Registration Channel)
# ============================================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # --- Registration format check ---
    if message.channel.id == REGISTRATION_CHANNEL_ID:
        valid, result = check_registration_format(message.content)
        if valid:
            await message.add_reaction("✅")
            # Save team data
            data = load_data()
            slot_teams = data.get("slot_teams", [])
            team_info = {
                "team_name": result["team_name"],
                "players": result["players"],
                "user_id": str(message.author.id),
                "message_id": str(message.id)
            }
            slot_teams.append(team_info)
            data["slot_teams"] = slot_teams
            save_data(data)

            # Auto lock after 25 teams
            if len(slot_teams) >= MAX_TEAMS_PER_SLOT:
                channel = message.channel
                await channel.set_permissions(
                    message.guild.default_role,
                    send_messages=False
                )
                await channel.send(
                    "🔒 **Registration Full!** 25 teams register ho gayi hain. Channel lock ho gaya hai."
                )
                # Assign plot numbers
                await assign_plots(message.guild, slot_teams, channel)
        else:
            await message.add_reaction("❌")
            try:
                await message.author.send(
                    f"**X TOURNEYS Registration Error**\n\n{result}\n\n"
                    f"**Sahi Format:**\n"
                    f"```\nTeam name - YourTeamName\n"
                    f"Team players name -\n"
                    f"@player1\n@player2\n@player3\n@player4\n```"
                )
            except:
                pass

    # --- Result submission check ---
    if message.channel.id == RESULT_SUBMIT_CHANNEL_ID:
        await process_result_submission(message)

    await bot.process_commands(message)

# ============================================================
#   FUNCTION 2: ASSIGN PLOTS after 25 teams register
# ============================================================
async def assign_plots(guild, slot_teams, channel):
    plot_message = "**📋 PLOT ASSIGNMENTS**\n\n"
    data = load_data()
    plots = {}

    for i, team in enumerate(slot_teams, 1):
        plot_message += f"**Plot {i}** — {team['team_name']}\n"
        plots[str(i)] = team

    data["plots"] = plots
    data["slot_teams"] = []
    save_data(data)

    await channel.send(plot_message)

# ============================================================
#   FUNCTION 3: AUTO LOCK/UNLOCK CATEGORY CHANNELS
# ============================================================
@tasks.loop(minutes=1)
async def auto_lock_unlock():
    now = datetime.now(IST)
    guild = bot.get_guild(SERVER_ID)
    if not guild:
        return

    category = guild.get_channel(CATEGORY_ID)
    if not category or not isinstance(category, discord.CategoryChannel):
        return

    # Unlock at 2:00 PM IST
    if now.hour == REGISTRATION_HOUR and now.minute == 0:
        data = load_data()
        data["slot_teams"] = []
        save_data(data)
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(
                    guild.default_role,
                    send_messages=True
                )
        print(f"✅ Category unlocked at {now.strftime('%H:%M')} IST")

# ============================================================
#   FUNCTION 4: 4 PM PRIVATE PLOT MESSAGE
# ============================================================
@tasks.loop(minutes=1)
async def daily_slot_announce():
    now = datetime.now(IST)
    guild = bot.get_guild(SERVER_ID)
    if not guild:
        return

    if now.hour == ANNOUNCE_HOUR and now.minute == 0:
        data = load_data()
        plots = data.get("plots", {})
        if not plots:
            return

        reg_channel = guild.get_channel(REGISTRATION_CHANNEL_ID)

        for plot_num, team in plots.items():
            player_ids = team.get("players", [])
            msg = (
                f"🎮 **YOUR MATCH DETAILS**\n\n"
                f"**Plot Number:** {plot_num}\n"
                f"**Team Name:** {team['team_name']}\n"
                f"**Match Time:** 4:00 PM IST\n\n"
                f"Good luck! 🏆"
            )
            # Send ephemeral-style: mention each player so only they see via DM
            for pid in player_ids:
                try:
                    uid = int(pid.replace("<@", "").replace(">", "").replace("!", ""))
                    member = guild.get_member(uid)
                    if member:
                        await member.send(msg)
                except Exception as e:
                    print(f"DM error: {e}")

        # Clear plots after sending
        data["plots"] = {}
        save_data(data)
        print(f"✅ 4PM plot messages sent at {now.strftime('%H:%M')} IST")

# ============================================================
#   FUNCTION 5: RESULT SUBMISSION PROCESSING
# ============================================================
async def process_result_submission(message):
    """
    Bot reads result submission: screenshot + match details
    Validates and adds tick reaction
    """
    has_image = len(message.attachments) > 0
    has_text  = len(message.content.strip()) > 10

    if has_image and has_text:
        await message.add_reaction("✅")
        # Save result
        results = load_results()
        week_key = get_current_week_key()
        if week_key not in results["weekly_results"]:
            results["weekly_results"][week_key] = []

        # Extract team info from message
        content = message.content
        results["weekly_results"][week_key].append({
            "user_id": str(message.author.id),
            "content": content,
            "message_id": str(message.id),
            "timestamp": datetime.now(IST).isoformat(),
            "first_place": detect_first_place(content)
        })

        # Update team stats
        update_team_stats(results, message.author.id, content)
        save_results(results)
    else:
        await message.add_reaction("❌")
        try:
            await message.author.send(
                "❌ **Result submission incomplete!**\n\n"
                "Please submit:\n"
                "1. Final result **screenshot**\n"
                "2. Match **time and date details** in text\n\n"
                "Both are required!"
            )
        except:
            pass

def detect_first_place(content):
    content_lower = content.lower()
    return any(word in content_lower for word in ["#1", "1st", "first", "winner", "1 place", "rank 1"])

def get_current_week_key():
    now = datetime.now(IST)
    start = now - timedelta(days=now.weekday())
    return start.strftime("%Y-%W")

def update_team_stats(results, user_id, content):
    uid = str(user_id)
    if uid not in results["team_stats"]:
        results["team_stats"][uid] = {
            "matches_played": 0,
            "first_place_count": 0,
            "top3_count": 0,
            "team_name": "Unknown"
        }
    results["team_stats"][uid]["matches_played"] += 1
    if detect_first_place(content):
        results["team_stats"][uid]["first_place_count"] += 1
    top3_keywords = ["#1","#2","#3","1st","2nd","3rd","top 3","top3"]
    if any(k in content.lower() for k in top3_keywords):
        results["team_stats"][uid]["top3_count"] += 1

# ============================================================
#   FUNCTION 6: WEEKLY LEADERBOARD (Every Monday)
# ============================================================
@tasks.loop(minutes=1)
async def weekly_leaderboard():
    now = datetime.now(IST)
    guild = bot.get_guild(SERVER_ID)
    if not guild:
        return

    # Every Monday at 10:00 AM IST
    if now.weekday() == 0 and now.hour == 10 and now.minute == 0:
        await generate_and_post_leaderboard(guild)

async def generate_and_post_leaderboard(guild):
    results     = load_results()
    week_key    = get_current_week_key()
    weekly_data = results.get("weekly_results", {}).get(week_key, [])
    team_stats  = results.get("team_stats", {})

    if not weekly_data and not team_stats:
        return

    # Sort by first place count
    sorted_teams = sorted(
        team_stats.items(),
        key=lambda x: (x[1]["first_place_count"], x[1]["top3_count"]),
        reverse=True
    )[:10]

    # Generate leaderboard image
    img = create_leaderboard_image(sorted_teams, guild)

    lb_channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if lb_channel and img:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="leaderboard.png")

        # Tag top 3 for T2 qualify
        tag_msg = "🏆 **T3 WEEKLY LEADERBOARD — X TOURNEYS**\n\n"
        t2_role = discord.utils.get(guild.roles, name=T2_QUALIFY_ROLE_NAME)

        top3_mentions = []
        for i, (uid, stats) in enumerate(sorted_teams[:3], 1):
            try:
                member = guild.get_member(int(uid))
                if member:
                    top3_mentions.append(member.mention)
                    if t2_role and t2_role not in member.roles:
                        await member.add_roles(t2_role)
            except:
                pass

        if top3_mentions:
            tag_msg += f"🎉 Congratulations {', '.join(top3_mentions)}!\n"
            tag_msg += f"You got **T2 QUALIFY 🏆** role!\n\n"

        await lb_channel.send(tag_msg, file=file)

    # Post qualified players to T2 channel
    await post_t2_qualified(guild, sorted_teams)

    # Reset weekly data
    results["weekly_results"][week_key] = []
    save_results(results)

# ============================================================
#   FUNCTION 7: CREATE LEADERBOARD IMAGE
# ============================================================
def create_leaderboard_image(sorted_teams, guild):
    try:
        width, height = 900, 700
        img = Image.new("RGB", (width, height), color=(15, 15, 30))
        draw = ImageDraw.Draw(img)

        # Background gradient effect
        for y in range(height):
            r = int(15 + (y / height) * 20)
            g = int(15 + (y / height) * 10)
            b = int(30 + (y / height) * 40)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Title
        try:
            font_title  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
            font_sub    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
            font_normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except:
            font_title  = ImageFont.load_default()
            font_sub    = font_title
            font_normal = font_title

        # Server name
        draw.text((width//2, 40), "X TOURNEYS", font=font_title,
                  fill=(255, 215, 0), anchor="mm")
        draw.text((width//2, 90), "T3 TOURNAMENT — WEEKLY LEADERBOARD",
                  font=font_sub, fill=(200, 200, 255), anchor="mm")

        week_str = datetime.now(IST).strftime("Week of %d %B %Y")
        draw.text((width//2, 120), week_str, font=font_normal,
                  fill=(150, 150, 200), anchor="mm")

        # Divider
        draw.line([(50, 140), (850, 140)], fill=(255, 215, 0), width=2)

        # Headers
        draw.text((80,  160), "RANK", font=font_sub, fill=(255, 215, 0))
        draw.text((200, 160), "TEAM",  font=font_sub, fill=(255, 215, 0))
        draw.text((550, 160), "#1 WINS", font=font_sub, fill=(255, 215, 0))
        draw.text((700, 160), "MATCHES", font=font_sub, fill=(255, 215, 0))

        draw.line([(50, 190), (850, 190)], fill=(100, 100, 150), width=1)

        medals = ["🥇", "🥈", "🥉"]
        y_pos  = 205

        for i, (uid, stats) in enumerate(sorted_teams[:10], 1):
            row_color = (255, 215, 0) if i <= 3 else (220, 220, 220)
            bg_color  = (30, 30, 60)  if i % 2 == 0 else (25, 25, 50)
            draw.rectangle([(50, y_pos-5), (850, y_pos+30)], fill=bg_color)

            rank_text = medals[i-1] if i <= 3 else f"#{i}"
            draw.text((80,  y_pos), rank_text, font=font_sub, fill=row_color)
            draw.text((200, y_pos), stats.get("team_name", f"Team {uid[:6]}"),
                      font=font_normal, fill=row_color)
            draw.text((570, y_pos), str(stats["first_place_count"]),
                      font=font_sub, fill=row_color)
            draw.text((720, y_pos), str(stats["matches_played"]),
                      font=font_sub, fill=row_color)

            y_pos += 40

        # Footer
        draw.line([(50, y_pos+10), (850, y_pos+10)], fill=(255, 215, 0), width=2)
        draw.text((width//2, y_pos+30), "Good luck next week! 🏆",
                  font=font_sub, fill=(150, 255, 150), anchor="mm")

        return img

    except Exception as e:
        print(f"Image generation error: {e}")
        return None

# ============================================================
#   FUNCTION 8: POST T2 QUALIFIED PLAYERS
# ============================================================
async def post_t2_qualified(guild, sorted_teams):
    """
    Post teams that qualify for T2:
    - 15+ first place wins AND 6+ top-3 finishes in a week
    """
    t2_channel = guild.get_channel(T2_QUALIFY_CHANNEL_ID)
    if not t2_channel:
        return

    results   = load_results()
    week_key  = get_current_week_key()
    team_stats= results.get("team_stats", {})
    t2_role   = discord.utils.get(guild.roles, name=T2_QUALIFY_ROLE_NAME)

    qualified = []
    for uid, stats in team_stats.items():
        if stats["first_place_count"] >= 15 and stats["top3_count"] >= 6:
            qualified.append((uid, stats))

    if not qualified:
        await t2_channel.send(
            f"📊 **T2 QUALIFICATION UPDATE — {datetime.now(IST).strftime('%d %B %Y')}**\n\n"
            "No teams qualified for T2 this week. Keep grinding! 💪"
        )
        return

    msg = f"🏆 **T2 QUALIFIED TEAMS — {datetime.now(IST).strftime('%d %B %Y')}**\n\n"
    msg += "Congratulations to the following teams who qualified for **T2**!\n"
    msg += "*(15+ wins & 6+ Top 3 finishes this week)*\n\n"

    for uid, stats in qualified:
        try:
            member = guild.get_member(int(uid))
            name   = member.mention if member else f"User {uid}"
            msg   += (
                f"✅ **{stats.get('team_name', 'Unknown Team')}** — {name}\n"
                f"   🥇 First Place: {stats['first_place_count']} times\n"
                f"   🎮 Matches Played: {stats['matches_played']}\n"
                f"   🏅 Top 3: {stats['top3_count']} times\n\n"
            )
            if member and t2_role and t2_role not in member.roles:
                await member.add_roles(t2_role)
        except Exception as e:
            print(f"T2 qualify error: {e}")

    await t2_channel.send(msg)

# ============================================================
#   ADMIN COMMANDS
# ============================================================
@bot.command(name="forceleaderboard")
@commands.has_permissions(administrator=True)
async def force_leaderboard(ctx):
    """Force post leaderboard manually"""
    await ctx.send("📊 Leaderboard generate ho raha hai...")
    await generate_and_post_leaderboard(ctx.guild)
    await ctx.send("✅ Done!")

@bot.command(name="resetweek")
@commands.has_permissions(administrator=True)
async def reset_week(ctx):
    """Reset weekly data"""
    results = load_results()
    week_key = get_current_week_key()
    results["weekly_results"][week_key] = []
    results["team_stats"] = {}
    save_results(results)
    await ctx.send("✅ Weekly data reset ho gaya!")

@bot.command(name="stats")
async def show_stats(ctx, member: discord.Member = None):
    """Show stats of a player"""
    target = member or ctx.author
    results = load_results()
    stats = results["team_stats"].get(str(target.id))
    if not stats:
        await ctx.send(f"❌ {target.mention} ka koi data nahi mila abhi tak.")
        return
    embed = discord.Embed(
        title=f"📊 Stats — {target.display_name}",
        color=discord.Color.gold()
    )
    embed.add_field(name="🥇 First Place Wins", value=stats["first_place_count"])
    embed.add_field(name="🎮 Matches Played",   value=stats["matches_played"])
    embed.add_field(name="🏅 Top 3 Finishes",   value=stats["top3_count"])
    await ctx.send(embed=embed)

@bot.command(name="unlock")
@commands.has_permissions(administrator=True)
async def manual_unlock(ctx):
    """Manually unlock registration channel"""
    guild = ctx.guild
    category = guild.get_channel(CATEGORY_ID)
    if category:
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(guild.default_role, send_messages=True)
        await ctx.send("✅ Category channels unlock ho gaye!")
    else:
        await ctx.send("❌ Category nahi mila!")

@bot.command(name="lock")
@commands.has_permissions(administrator=True)
async def manual_lock(ctx):
    """Manually lock registration channel"""
    guild = ctx.guild
    category = guild.get_channel(CATEGORY_ID)
    if category:
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(guild.default_role, send_messages=False)
        await ctx.send("✅ Category channels lock ho gaye!")
    else:
        await ctx.send("❌ Category nahi mila!")

@bot.command(name="setteamname")
async def set_team_name(ctx, *, name: str):
    """Set your team name"""
    results = load_results()
    uid = str(ctx.author.id)
    if uid not in results["team_stats"]:
        results["team_stats"][uid] = {
            "matches_played": 0, "first_place_count": 0,
            "top3_count": 0, "team_name": name
        }
    else:
        results["team_stats"][uid]["team_name"] = name
    save_results(results)
    await ctx.send(f"✅ Team name set ho gaya: **{name}**")

@bot.command(name="rkmhelp")
async def rkm_help(ctx):
    embed = discord.Embed(
        title="🤖 RKM Bot — Commands",
        color=discord.Color.gold(),
        description="X TOURNEYS Official Bot"
    )
    embed.add_field(name="!stats [@member]",        value="Player/team stats dekho",       inline=False)
    embed.add_field(name="!setteamname <name>",     value="Apna team name set karo",        inline=False)
    embed.add_field(name="!unlock (Admin)",         value="Registration channel unlock karo",inline=False)
    embed.add_field(name="!lock (Admin)",           value="Registration channel lock karo", inline=False)
    embed.add_field(name="!forceleaderboard (Admin)",value="Turant leaderboard post karo",  inline=False)
    embed.add_field(name="!resetweek (Admin)",      value="Weekly data reset karo",         inline=False)
    embed.set_footer(text="X TOURNEYS — RKM Bot")
    await ctx.send(embed=embed)

# ============================================================
#                    RUN BOT
# ============================================================
if __name__ == "__main__":
    bot.run(TOKEN)
