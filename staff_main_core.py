from flask import Blueprint, render_template, request, session, redirect,url_for
import mariadb
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')

# Database connection
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

@staff_bp.route("/staff_main", methods=["GET"])
def staff_main():
    if "user_id" not in session or session.get("role") != "Staff":
        return redirect("/login")

    user_id = session["user_id"]
    
    # Filters
    keyword = request.args.get("keyword", "")
    ticket_type = request.args.get("ticket_type", "")
    status = request.args.get("status", "")
    urgency = request.args.get("urgency", "")
    date = request.args.get("date", "")

    filters = []
    params = [user_id]  # Always filter by assigner_id

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

    # Base query - always show tickets assigned to current user
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
        WHERE t.assigner_id = %s
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
        "staff_main.html",
        tickets=tickets,
        ticket_types=ticket_types,
        urgency_levels=urgency_levels
    )
@staff_bp.route("/staff/ticket/<ticket_id>", methods=["GET", "POST"])
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
@staff_bp.route('/reset_filters')
def reset_filters():
    # Simply redirect to the main page without any query parameters
    return redirect(url_for('staff.staff_main'))

@staff_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('staff.staff_main'))