from flask import Blueprint, render_template, session, redirect, request
import mariadb
import os
from dotenv import load_dotenv
from datetime import datetime

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
user_bp = Blueprint('user', __name__, url_prefix='/user')

@user_bp.route('/dashboard', methods=["GET"])
def user_dashboard():
    if 'user_id' not in session or session.get('role') != 'User':
        return redirect('/login')

    user_id = session['user_id']

    # Get filter values from query params
    status = request.args.get("status")
    urgency = request.args.get("urgency")
    type_id = request.args.get("type_id")
    search = request.args.get("search")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    sort_by = request.args.get("sort_by", "create_date")  # Default: create_date
    sort_dir = request.args.get("sort_dir", "desc")        # Default: descending

    # Validate allowed sort fields to avoid SQL injection
    allowed_sort_fields = ["create_date", "last_update"]
    if sort_by not in allowed_sort_fields:
        sort_by = "create_date"
    if sort_dir.lower() not in ["asc", "desc"]:
        sort_dir = "desc"

    # Build dynamic SQL with filters
    query = """
        SELECT 
            t.ticket_id, t.title, t.description, t.status, 
            t.create_date, t.last_update, 
            tt.type_name,
            u.urgency,
            r.username AS reporter_username,
            a.username AS assigner_username
        FROM Tickets t
        JOIN TicketTypes tt ON t.type = tt.type_id
        JOIN Accounts r ON t.reporter_id = r.user_id
        LEFT JOIN Accounts a ON t.assigner_id = a.user_id
        LEFT JOIN Urgencylevel u ON t.urgency = u.level
        WHERE t.reporter_id = %s
    """
    params = [user_id]

    if status:
        query += " AND t.status = %s"
        params.append(status)

    if urgency:
        query += " AND u.urgency = %s"
        params.append(urgency)

    if type_id:
        query += " AND t.type = %s"
        params.append(type_id)

    if search:
        query += " AND (t.title LIKE %s OR r.username LIKE %s OR a.username LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])

    if start_date:
        query += " AND DATE(t.create_date) >= %s"
        params.append(start_date)

    if end_date:
        query += " AND DATE(t.create_date) <= %s"
        params.append(end_date)

    query += f" ORDER BY t.{sort_by} {sort_dir.upper()}"

    cursor.execute(query, tuple(params))
    tickets = cursor.fetchall()

    # Fetch all ticket types for dropdown
    cursor.execute("SELECT type_id, type_name FROM TicketTypes")
    ticket_types = cursor.fetchall()

    return render_template(
        "user_main.html",
        tickets=tickets,
        username=session.get('username'),
        ticket_types=ticket_types,
        selected_status=status,
        selected_urgency=urgency,
        selected_type=type_id,
        search_query=search,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_dir=sort_dir
    )

@user_bp.route('/ticket/<ticket_id>', methods=['GET', 'POST'])
def view_ticket(ticket_id):
    user_id = session.get("user_id")
    if not user_id:
        return "Unauthorized", 401

    # Fetch ticket with full join info
    cursor.execute("""
        SELECT t.*, tt.type_name, u.urgency,
               ra.username AS reporter_username,
               aa.username AS assigner_username
        FROM Tickets t
        JOIN TicketTypes tt ON t.type = tt.type_id
        JOIN Urgencylevel u ON t.urgency = u.level
        JOIN Accounts ra ON t.reporter_id = ra.user_id
        LEFT JOIN Accounts aa ON t.assigner_id = aa.user_id
        WHERE t.ticket_id = ? AND t.reporter_id = ?
    """, (ticket_id, user_id))
    ticket = cursor.fetchone()

    if not ticket:
        return "Ticket not found or access denied.", 404

    # Handle form submission
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save':
            new_description = request.form.get('description')
            cursor.execute("""
                UPDATE Tickets
                SET description = ?, last_update = ?
                WHERE ticket_id = ? AND reporter_id = ?
            """, (new_description, datetime.now(), ticket_id, user_id))
            conn.commit()
        elif action == 'close':
            cursor.execute("""
                UPDATE Tickets
                SET status = 'Closed', last_update = ?
                WHERE ticket_id = ? AND reporter_id = ?
            """, (datetime.now(), ticket_id, user_id))
            conn.commit()
        elif action == 'reject':
            cursor.execute("""
                UPDATE Tickets
                SET status = 'Reject', last_update = ?
                WHERE ticket_id = ? AND reporter_id = ?
            """, (datetime.now(), ticket_id, user_id))
            conn.commit()
        return redirect(url_for('user.view_ticket', ticket_id=ticket_id))

    return render_template("user_view_ticket.html", ticket=ticket)
