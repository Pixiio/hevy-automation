import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

# ==========================================
# CONFIG
# ==========================================

HEVY_API_KEY = os.environ.get("HEVY_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

HEVY_API_URL = "https://api.hevyapp.com/v1"

REP_MIN = 8
REP_MAX = 12
PROGRESSION_RPE_TRIGGER = 9

ROUNDING = 0.5


# ==========================================
# HELPERS
# ==========================================

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


def set_score(weight, reps):
    return weight * reps


# ==========================================
# API
# ==========================================

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


# ==========================================
# ANALYSIS
# ==========================================

def best_set(sets):

    best = None
    best_score = 0

    for s in sets:

        weight = s.get("weight_kg") or 0
        reps = s.get("reps") or 0

        score = set_score(weight,reps)

        if score > best_score:
            best_score = score
            best = s

    return best


def find_pr(exercise_name, workouts):

    best_score_val = 0

    for w in workouts:

        for ex in w.get("exercises",[]):

            if ex.get("title") != exercise_name:
                continue

            for s in ex.get("sets",[]):

                score = set_score(
                    s.get("weight_kg") or 0,
                    s.get("reps") or 0
                )

                if score > best_score_val:
                    best_score_val = score

    return best_score_val


def plateau_detect(exercise_name, workouts):

    weights = []

    for w in workouts:

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


# ==========================================
# PROGRESSION
# ==========================================

def calculate_next_target(exercise_name, sets, history):

    working = best_set(sets)

    if not working:
        return None

    reps = working.get("reps") or 0
    weight = round(working.get("weight_kg") or 0,1)
    rpe = working.get("rpe") or 8

    increment = get_increment(exercise_name)

    pr_score = find_pr(exercise_name,history)

    score = set_score(weight,reps)

    plateau = plateau_detect(exercise_name,history)

    badge_color="#e2e3e5"
    text_color="#383d41"

    # =====================================
    # PROGRESSION RULES
    # =====================================

    if score >= pr_score and reps>=REP_MIN:

        badge_color="#ffeeba"
        text_color="#856404"

        pr_tag=" 🏆 PR"
    else:
        pr_tag=""

    if plateau:

        new_weight = round_weight(weight*0.9)

        action="DELOAD"
        target=f"Reset: {new_weight} kg"

        badge_color="#f8d7da"
        text_color="#721c24"

    elif reps >= REP_MAX and rpe <= PROGRESSION_RPE_TRIGGER:

        new_weight = round_weight(weight+increment)

        action="INCREASE WEIGHT"
        target=f"{new_weight} kg"

        badge_color="#d4edda"
        text_color="#155724"

    elif reps < REP_MAX:

        action="ADD REPS"
        target=f"{min(reps+1,REP_MAX)} reps"

        badge_color="#cce5ff"
        text_color="#004085"

    else:

        action="MAINTAIN"
        target="Try +1 rep"

    return {
        "exercise":exercise_name,
        "last":f"{reps} @ {weight} kg (RPE {rpe}){pr_tag}",
        "action":action,
        "target_display":target,
        "badge_color":badge_color,
        "text_color":text_color
    }


# ==========================================
# EMAIL
# ==========================================

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


# ==========================================
# MAIN
# ==========================================

if __name__=="__main__":

    week_workouts=fetch_workouts(7)
    history_workouts=fetch_workouts(28)

    routines={}

    for w in week_workouts:

        title=w.get("title","Workout")

        if title not in routines:
            routines[title]=w

    end_date=datetime.now().strftime("%b %d")
    start_date=(datetime.now()-timedelta(days=7)).strftime("%b %d")

    html=f"""
<html>
<body style="background:#f6f9fc;font-family:Arial;padding:20px;">
<h1>Next Week Targets</h1>
<p>{start_date} - {end_date}</p>
"""

    text=f"Training plan {start_date}-{end_date}\n\n"

    for title,data in routines.items():

        date=data["start_time"].replace("Z","+00:00")
        day=datetime.fromisoformat(date).strftime("%A")

        html+=f"<h2>{title}</h2><p>{day}</p>"

        for ex in data.get("exercises",[]):

            res=calculate_next_target(
                ex.get("title"),
                ex.get("sets",[]),
                history_workouts
            )

            if not res:
                continue

            html+=f"""
<p>
<b>{res['exercise']}</b><br>
{res['last']}<br>
<b>{res['action']}</b> → {res['target_display']}
</p>
"""

            text+=f"{res['exercise']} → {res['target_display']}\n"

    html+="</body></html>"

    send_email(html,text,start_date,end_date)
