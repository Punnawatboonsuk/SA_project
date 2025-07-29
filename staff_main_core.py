from flask import Blueprint, render_template, request, session, redirect
import mariadb
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

staff_dashboard = Blueprint("staff_dashboard", __name__)

# Database connection
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

@staff_dashboard.route("/staff_main", methods=["GET"])
def staff_main():
    if "user_id" not in session or session.get("role") != "Staff":
        return redirect("/login")

    user_id = session["user_id"]
    view_mode = request.args.get("view", "all")  # "all" or "assigned"

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

    if view_mode == "assigned":
        base_query += " WHERE t.assigner_id = %s AND t.status IN ('Assigned', 'Reject')"
        params = [user_id] + params
    else:  # 'all' mode - tickets of matching type & status open
        base_query += """
            JOIN Staffspeciality s ON t.type = s.type_id
            WHERE t.status = 'Open' AND s.user_id = %s
        """
        params = [user_id] + params

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
        "staff_main.html",
        tickets=tickets,
        ticket_types=ticket_types,
        urgency_levels=urgency_levels,
        view_mode=view_mode
    )
@staff_bp.route('/ticket/<ticket_id>', methods=['GET', 'POST'])
def view_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        return "Unauthorized", 401

    user_id = session["user_id"]

    # Fetch the ticket with all necessary joins
    cursor.execute("""
        SELECT t.*, tt.type_name, u.urgency,
               ra.username AS reporter_username,
               aa.username AS assigner_username
        FROM Tickets t
        JOIN TicketTypes tt ON t.type = tt.type_id
        JOIN Urgencylevel u ON t.urgency = u.level
        JOIN Accounts ra ON t.reporter_id = ra.user_id
        LEFT JOIN Accounts aa ON t.assigner_id = aa.user_id
        WHERE t.ticket_id = ?
    """, (ticket_id,))
    ticket = cursor.fetchone()

    if not ticket:
        return "Ticket not found.", 404

    # Handle form submission for Assign / Resolve
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'assign' and ticket['status'] == 'Open':
            cursor.execute("""
                UPDATE Tickets
                SET status = 'Assigned', assigner_id = ?, last_update = ?
                WHERE ticket_id = ?
            """, (user_id, datetime.now(), ticket_id))
            conn.commit()

        elif action == 'resolve' and ticket['status'] in ('Assigned', 'Reject'):
            cursor.execute("""
                UPDATE Tickets
                SET status = 'Resolved', last_update = ?
                WHERE ticket_id = ?
            """, (datetime.now(), ticket_id))
            conn.commit()

        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

    return render_template("staff_ticket_detail.html", ticket=ticket)
