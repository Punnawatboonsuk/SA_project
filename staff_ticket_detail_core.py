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
        now = datetime.now()

        if action == "work":
            # Change status to Assign-working_on if currently Assign-in_queue
            cursor.execute("""
                UPDATE Tickets 
                SET status = 'Assign-working_on', last_update = %s 
                WHERE ticket_id = %s AND assigner_id = %s AND status = 'Assign-in_queue'
            """, (now, ticket_id, staff_id))
            conn.commit()

        elif action == "finish":
            # Change status to in_checking if currently Assign-working_on
            cursor.execute("""
                UPDATE Tickets 
                SET status = 'in_checking', last_update = %s 
                WHERE ticket_id = %s AND assigner_id = %s AND status = 'Assign-working_on'
            """, (now, ticket_id, staff_id))
            conn.commit()

        elif action == "reassign":
            # Change status to Reassigning if currently Assign-in_queue or Assign-working_on
            cursor.execute("""
                UPDATE Tickets 
                SET status = 'Reassigning', last_update = %s 
                WHERE ticket_id = %s AND assigner_id = %s AND status IN ('Assign-in_queue', 'Assign-working_on')
            """, (now, ticket_id, staff_id))
            conn.commit()

        return redirect(url_for("staff_view_ticket", ticket_id=ticket_id))

    # Fetch ticket detail with related information
    cursor.execute("""
        SELECT t.*, ty.type_name, ul.level_name AS urgency_name,
               a.username AS reporter_name,
               b.username AS assigner_name
        FROM Tickets t
        LEFT JOIN TicketType ty ON t.type = ty.type_id
        LEFT JOIN UrgencyLevel ul ON t.urgency = ul.level_id
        LEFT JOIN Accounts a ON t.reporter_id = a.user_id
        LEFT JOIN Accounts b ON t.assigner_id = b.user_id
        WHERE t.ticket_id = %s AND t.assigner_id = %s
    """, (ticket_id, staff_id))
    ticket = cursor.fetchone()

    if not ticket:
        return "Ticket not found or you are not assigned to it", 404

    # Determine which buttons to show based on status
    show_work_button = (ticket["status"] == "Assign-in_queue")
    show_finish_button = (ticket["status"] == "Assign-working_on")
    show_reassign_button = (ticket["status"] in ["Assign-in_queue", "Assign-working_on"])

    return render_template(
        "staff_ticket_detail.html",
        ticket=ticket,
        show_work_button=show_work_button,
        show_finish_button=show_finish_button,
        show_reassign_button=show_reassign_button
    )