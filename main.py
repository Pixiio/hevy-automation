import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

HEVY_API_KEY = os.environ.get("HEVY_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

HEVY_API_URL = "https://api.hevyapp.com/v1"

REP_MIN = 8
REP_MAX = 12
ROUNDING = 0.5


def round_weight(weight):
    return round(weight / ROUNDING) * ROUNDING


def get_increment(name):

    name = name.lower()

    if "dumbbell" in name:
        return 2

    if "machine" in name:
        return 5

    if "cable" in name:
        return 5

    if "barbell" in name or "smith" in name:
        return 2.5

    return 2.5


def best_set(sets):

    best = None
    best_score = 0

    for s in sets:

        w = s.get("weight_kg") or 0
        r = s.get("reps") or 0

        score = w * r

        if score > best_score:
            best_score = score
            best = s

    return best


def fetch_workouts(days):

    headers = {"api-key": HEVY_API_KEY, "accept": "application/json"}

    workouts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for page in range(1,6):

        r = requests.get(
            f"{HEVY_API_URL}/workouts",
            headers=headers,
            params={"page":page,"pageSize":10}
        )

        if r.status_code != 200:
            break

        data = r.json().get("workouts",[])

        if not data:
            break

        for w in data:

            date = w["start_time"].replace("Z","+00:00")
            d = datetime.fromisoformat(date)

            if d >= cutoff:
                workouts.append(w)
            else:
                return workouts

    return workouts


def detect_plateau(exercise_name, history):

    weights = []

    for w in history:

        for ex in w.get("exercises",[]):

            if ex.get("title") != exercise_name:
                continue

            b = best_set(ex.get("sets",[]))
            if not b:
                continue

            weights.append(b.get("weight_kg") or 0)

    if len(weights) < 3:
        return False

    return weights[-1] == weights[-2] == weights[-3]


def calculate_next_target(exercise_name, sets, history):

    working = best_set(sets)

    if not working:
        return None

    reps = working.get("reps") or 0
    weight = round(working.get("weight_kg") or 0,1)
    rpe = working.get("rpe") or 8

    increment = get_increment(exercise_name)

    plateau = detect_plateau(exercise_name, history)

    if plateau:

        new_weight = round_weight(weight * 0.9)

        action = "DELOAD"
        target = f"Reset to {new_weight} kg"

        badge_color="#f8d7da"
        text_color="#721c24"

    elif reps >= REP_MAX:

        new_weight = round_weight(weight + increment)

        action="INCREASE WEIGHT"
        target=f"Target: {new_weight} kg"

        badge_color="#d4edda"
        text_color="#155724"

    elif reps < REP_MAX:

        action="ADD REPS"
        target=f"Target: {reps+1} reps"

        badge_color="#cce5ff"
        text_color="#004085"

    else:

        action="MAINTAIN"
        target="Try +1 rep"

        badge_color="#e2e3e5"
        text_color="#383d41"

    return {
        "exercise":exercise_name,
        "last":f"{reps} @ {weight} kg (RPE {rpe})",
        "action":action,
        "target_display":target,
        "badge_color":badge_color,
        "text_color":text_color
    }


def send_email(html_body,text_body,start,end):

    msg=MIMEMultipart("alternative")

    msg["From"]=EMAIL_SENDER
    msg["To"]=EMAIL_RECEIVER
    msg["Subject"]=f"Weekly Training Plan ({start} - {end})"

    msg.attach(MIMEText(text_body,"plain"))
    msg.attach(MIMEText(html_body,"html"))

    s=smtplib.SMTP("smtp.gmail.com",587)
    s.starttls()
    s.login(EMAIL_SENDER,EMAIL_PASSWORD)
    s.send_message(msg)
    s.quit()


if __name__=="__main__":

    week_workouts = fetch_workouts(7)
    history = fetch_workouts(28)

    routines={}

    for w in week_workouts:

        title=w.get("title","Workout")

        if title not in routines:
            routines[title]=w

    end_date=datetime.now().strftime("%b %d")
    start_date=(datetime.now()-timedelta(days=7)).strftime("%b %d")

    html_content=f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f6f9fc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto;">
<table width="100%" style="padding:20px;">
<tr>
<td align="center">

<table width="600" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.05);">

<tr>
<td style="background:#212529;padding:30px;text-align:center;">
<h1 style="color:#fff;margin:0;">Next Week's Targets</h1>
<p style="color:#adb5bd;">Review of {start_date} - {end_date}</p>
</td>
</tr>

<tr>
<td style="padding:40px;">
"""

    text_content=""

    for title,data in routines.items():

        raw_date=data["start_time"].replace("Z","+00:00")
        day=datetime.fromisoformat(raw_date).strftime("%A")

        html_content+=f"""
<div style="margin-bottom:30px;">

<div style="border-bottom:2px solid #eee;padding-bottom:10px;margin-bottom:15px;">
<h2 style="margin:0;">{title}</h2>
<span style="font-size:12px;color:#888;">Last Session: {day}</span>
</div>
"""

        for ex in data.get("exercises",[]):

            res=calculate_next_target(
                ex.get("title"),
                ex.get("sets",[]),
                history
            )

            if not res:
                continue

            badge_style=f"""
background-color:{res['badge_color']};
color:{res['text_color']};
padding:4px 8px;
border-radius:4px;
font-size:11px;
font-weight:bold;
"""

            html_content+=f"""
<div style="padding:12px 0;border-bottom:1px solid #f0f0f0;">

<table width="100%">
<tr>

<td width="60%">
<strong>{res['exercise']}</strong><br>
<span style="color:#999;">Top Set: {res['last']}</span>
</td>

<td width="40%" align="right">

<span style="{badge_style}">
{res['action']}
</span>

<div style="margin-top:5px;font-weight:600;">
{res['target_display']}
</div>

</td>
</tr>
</table>

</div>
"""

        html_content+="</div>"

    html_content+="""
</td>
</tr>

<tr>
<td style="background:#f8f9fa;padding:20px;text-align:center;">
Generated by Hevy Automation Script
</td>
</tr>

</table>
</td>
</tr>
</table>
</body>
</html>
"""

    send_email(html_content,text_content,start_date,end_date)
