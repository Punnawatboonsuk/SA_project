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

@mod_bp.route("/mod_main", methods=["GET"])
def mod_main():
    if "user_id" not in session or session.get("role") != "Mod":
        return redirect("/login")

    user_id = session["user_id"]
  

    # Filters
    keyword = request.args.get("keyword", "")
    ticket_type = request.args.get("ticket_type", "")
    status = request.args.get("status", "")
    urgency = request.args.get("urgency", "")
    date = request.args.get("date", "")

    filters = []
    params = []

    if keyword:
        filters.append("(t.title LIKE %s OR t.description LIKE %s OR ru.username LIKE %s OR au.username LIKE %s)")
        params.extend([f"%{keyword}%"] * 4)

    if ticket_type:
        filters.append("t.type = %s")
        params.append(ticket_type)

    if status:
        filters.append("t.status = %s")
        params.append(status)

    if urgency:
        filters.append("t.urgency = %s")
        params.append(urgency)

    if date:
        filters.append("DATE(t.create_date) = %s")
        params.append(date)

    # Base query
    base_query = """
        SELECT 
            t.ticket_id, t.title, t.description, t.status, t.create_date, t.last_update,
            tt.type_name, ul.level_name AS urgency,
            ru.username AS reporter_username,
            au.username AS assigner_username
        FROM Tickets t
        JOIN TicketType tt ON t.type = tt.type_id
        LEFT JOIN UrgencyLevel ul ON t.urgency = ul.level_id
        JOIN Accounts ru ON t.reporter_id = ru.user_id
        LEFT JOIN Accounts au ON t.assigner_id = au.user_id
    """

    if filters:
        base_query += " AND " + " AND ".join(filters)

    base_query += " ORDER BY t.last_update DESC"

    cursor.execute(base_query, tuple(params))
    tickets = cursor.fetchall()

    # Get ticket types for dropdown
    cursor.execute("SELECT * FROM TicketType")
    ticket_types = cursor.fetchall()

    # Get urgency levels for dropdown
    cursor.execute("SELECT * FROM UrgencyLevel")
    urgency_levels = cursor.fetchall()

    return render_template(
        "mod_main.html",
        tickets=tickets,
        ticket_types=ticket_types,
        urgency_levels=urgency_levels,
       
    )

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

        elif action == "out_of_service":
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

@mod_bp.route('/reset_filters')
def reset_filters():
    # Simply redirect to the main page without any query parameters
    return redirect(url_for('staff.staff_main'))

@mod_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('staff.staff_main'))