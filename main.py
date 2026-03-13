import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

# ==========================================
# CONFIGURATION
# ==========================================
HEVY_API_KEY = os.environ.get("HEVY_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

HEVY_API_URL = "https://api.hevyapp.com/v1"

# Progression settings
GOAL_REPS = 12
PROGRESSION_RPE_TRIGGER = 9
WEIGHT_INCREMENT_KG = 2.5
ROUNDING = 0.5


def round_weight(weight):
    return round(weight / ROUNDING) * ROUNDING


def get_weekly_workouts():
    headers = {
        "api-key": HEVY_API_KEY,
        "accept": "application/json"
    }

    all_workouts = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)

    print(f"Filtering workouts after {cutoff_date.strftime('%Y-%m-%d')}")

    for page in range(1, 4):
        try:
            params = {"page": page, "pageSize": 10}

            response = requests.get(
                f"{HEVY_API_URL}/workouts",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                break

            data = response.json()
            workouts = data.get("workouts", [])

            if not workouts:
                break

            for w in workouts:

                date_str = w.get("start_time", "")
                if date_str.endswith("Z"):
                    date_str = date_str.replace("Z", "+00:00")

                try:
                    w_date = datetime.fromisoformat(date_str)
                except ValueError:
                    continue

                if w_date >= cutoff_date:
                    all_workouts.append(w)
                else:
                    return all_workouts

        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break

    return all_workouts


def group_by_routine(workouts):

    routines = {}

    for w in workouts:
        title = w.get("title", "Workout")

        if title not in routines:
            routines[title] = w

    return routines


def calculate_next_target(exercise_name, sets):

    if not sets:
        return None

    # select heaviest set
    working_set = max(
        sets,
        key=lambda s: s.get("weight_kg") or 0
    )

    reps = working_set.get("reps") or 0
    weight_kg = round(working_set.get("weight_kg") or 0, 1)
    rpe = working_set.get("rpe") or 8

    if reps == 0:
        return None

    recommendation = {}

    # ==========================================
    # PROGRESSION LOGIC
    # ==========================================

    if reps >= GOAL_REPS and rpe <= PROGRESSION_RPE_TRIGGER:

        new_weight = round_weight(weight_kg + WEIGHT_INCREMENT_KG)

        recommendation = {
            "action": "INCREASE WEIGHT",
            "detail": f"Add {WEIGHT_INCREMENT_KG} kg",
            "target_display": f"Target: {new_weight} kg",
            "badge_color": "#d4edda",
            "text_color": "#155724"
        }

    elif reps < GOAL_REPS and rpe < 9:

        recommendation = {
            "action": "ADD REPS",
            "detail": f"Keep {weight_kg} kg",
            "target_display": f"Target: {min(reps+2, GOAL_REPS)} reps",
            "badge_color": "#cce5ff",
            "text_color": "#004085"
        }

    elif reps < (GOAL_REPS - 4) and rpe >= 9.5:

        new_weight = round_weight(weight_kg * 0.9)

        recommendation = {
            "action": "DELOAD",
            "detail": "Performance dip",
            "target_display": f"Reset to: {new_weight} kg",
            "badge_color": "#f8d7da",
            "text_color": "#721c24"
        }

    else:

        recommendation = {
            "action": "MAINTAIN",
            "detail": f"Keep {weight_kg} kg",
            "target_display": "Try +1 rep",
            "badge_color": "#e2e3e5",
            "text_color": "#383d41"
        }

    return {
        "exercise": exercise_name,
        "last": f"{reps} @ {weight_kg} kg (RPE {rpe})",
        **recommendation
    }


def send_email(html_body, text_body, start_date, end_date):

    msg = MIMEMultipart("alternative")

    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = f"Weekly Training Plan ({start_date} - {end_date})"

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()

        server.login(
            EMAIL_SENDER,
            EMAIL_PASSWORD
        )

        server.send_message(msg)
        server.quit()

        print("Email sent successfully")

    except Exception as e:

        print("Email failed:", e)


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    if not HEVY_API_KEY:
        print("HEVY_API_KEY missing")
        exit()

    print("Fetching workouts...")

    workouts = get_weekly_workouts()
    latest_routines = group_by_routine(workouts)

    if not latest_routines:
        print("No workouts found")
        exit()

    end_date = datetime.now().strftime("%b %d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%b %d")

    html_content = f"""
    <html>
    <body style="font-family:Arial;background:#f6f9fc;padding:20px;">
    <h1>Next Week Targets</h1>
    <p>Review of {start_date} - {end_date}</p>
    """

    text_content = f"Weekly Plan {start_date}-{end_date}\n\n"

    for title, data in latest_routines.items():

        raw_date = data["start_time"].replace("Z", "+00:00")
        display_date = datetime.fromisoformat(raw_date).strftime("%A")

        html_content += f"<h2>{title}</h2>"
        html_content += f"<p>Last session: {display_date}</p>"

        text_content += f"\n=== {title} ({display_date}) ===\n"

        for ex in data.get("exercises", []):

            result = calculate_next_target(
                ex.get("title"),
                ex.get("sets", [])
            )

            if not result:
                continue

            html_content += f"""
            <p>
            <b>{result['exercise']}</b><br>
            Last: {result['last']}<br>
            <b>{result['action']}</b> — {result['target_display']}
            </p>
            """

            text_content += f"{result['exercise']} -> {result['target_display']}\n"

    html_content += "</body></html>"

    send_email(
        html_content,
        text_content,
        start_date,
        end_date
    )
