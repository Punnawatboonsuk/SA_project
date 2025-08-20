import random
import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session
from dotenv import load_dotenv
import mariadb
load_dotenv()

# Setup DB connection
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

# Define Blueprint
mod_bp = Blueprint('mod', __name__, url_prefix='/mod')

@mod_bp.route("/mod/ticket/<ticket_id>", methods=["GET", "POST"])
def mod_view_ticket(ticket_id):
    if session.get("role") != "Mod":
        return "Unauthorized", 403

    mod_id = session.get("user_id")
    if not mod_id:
        return redirect("/login")

    today = datetime.now().strftime("%Y-%m-%d")

    # Handle button actions
    if request.method == "POST":
        action = request.form.get("action")
        selected_staff_id = request.form.get("selected_staff_id")  # From frontend

        if action == "assign":
            if selected_staff_id:  # Only assign if staff selected
                cursor.execute("""
                    UPDATE Tickets
                    SET status = 'Assigned-in queue', assigner_id = %s, last_update = %s
                    WHERE ticket_id = %s
                """, (selected_staff_id, today, ticket_id))
                conn.commit()

        elif action == "send_upper":
            cursor.execute("""
                UPDATE Tickets
                SET status = 'On going to upper level', last_update = %s
                WHERE ticket_id = %s
            """, (today, ticket_id))
            conn.commit()

        elif action == "out_service":
            cursor.execute("""
                UPDATE Tickets
                SET status = 'Out of service / outsource requirement', last_update = %s
                WHERE ticket_id = %s
            """, (today, ticket_id))
            conn.commit()

        return redirect(url_for("mod_view_ticket", ticket_id=ticket_id))

    # Fetch ticket detail
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

    # Fetch staff list with specialties
    cursor.execute("""
        SELECT 
    a.user_id,
    a.username,
    GROUP_CONCAT(DISTINCT s.speciality_name ORDER BY s.speciality_name SEPARATOR ', ') AS specialties
FROM Accounts a
JOIN StaffSpeciality s ON a.user_id = s.staff_id
JOIN Team t ON a.user_id = t.subor_id
WHERE a.role = 'Staff'
  AND t.Leader_id = %s
GROUP BY a.user_id, a.username;
    """,(mod_id))
    staff_list = cursor.fetchall()

    return render_template(
        "mod_ticket_detail.html",
        ticket=ticket,
        staff_list=staff_list,
        selected_staff_id=None  # Init as null/empty
    )
