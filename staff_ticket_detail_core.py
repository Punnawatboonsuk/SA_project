from flask import Flask, render_template, request, redirect, session, url_for
import mariadb
import os
from dotenv import load_dotenv
from datetime import datetime

# Load env variables
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Connect to DB
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

@app.route("/staff/ticket/<ticket_id>", methods=["GET", "POST"])
def staff_view_ticket(ticket_id):
    if session.get("role") != "Staff":
        return "Unauthorized", 403

    staff_id = session.get("user_id")
    if not staff_id:
        return redirect("/login")

    # Handle status change
    if request.method == "POST":
        action = request.form.get("action")
        today = datetime.now().strftime("%Y-%m-%d")

        if action == "assign":
            cursor.execute("""
                UPDATE Tickets 
                SET status = 'Assigned', assigner_id = %s, last_update = %s 
                WHERE ticket_id = %s AND status = 'Open'
            """, (staff_id, today, ticket_id))
            conn.commit()

        elif action == "resolve":
            cursor.execute("""
                UPDATE Tickets 
                SET status = 'Resolved', last_update = %s 
                WHERE ticket_id = %s AND assigner_id = %s AND status IN ('Assigned', 'Rejected')
            """, (today, ticket_id, staff_id))
            conn.commit()

        return redirect(url_for("staff_view_ticket", ticket_id=ticket_id))

    # Fetch ticket detail + type name
    cursor.execute("""
        SELECT t.*, ty.type_name, a.username AS reporter_name, b.username AS assigner_name
        FROM Tickets t
        LEFT JOIN TicketType ty ON t.type = ty.type_id
        LEFT JOIN Accounts a ON t.reporter_id = a.user_id
        LEFT JOIN Accounts b ON t.assigner_id = b.user_id
        WHERE t.ticket_id = %s
    """, (ticket_id,))
    ticket = cursor.fetchone()

    if not ticket:
        return "Ticket not found", 404

    # Determine which button to show
    action_button = None
    if ticket["status"] == "Open":
        action_button = "Assign"
    elif ticket["status"] in ("Assigned", "Rejected") and ticket["assigner_id"] == staff_id:
        action_button = "Resolve"

    return render_template("staff_ticket_detail.html", ticket=ticket, action_button=action_button)
