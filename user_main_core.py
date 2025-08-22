from flask import Blueprint, render_template, session, redirect, request, url_for, flash
import mariadb
import os
import random
from datetime import datetime
from app import logout
from dotenv import load_dotenv
load_dotenv()

# Define Blueprint
user_bp = Blueprint('user', __name__, url_prefix='/user')

# Database connection function
def get_db_connection():
    return mariadb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME")
    )

# User Dashboard
@user_bp.route('/user_main', methods=["GET"])
def user_dashboard():
    if 'user_id' not in session or session.get('role') != 'User':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Get filter values from query params
        status = request.args.get("status")
        urgency = request.args.get("urgency")
        type_id = request.args.get("type_id")
        search = request.args.get("search")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        sort_by = request.args.get("sort_by", "create_date")
        sort_dir = request.args.get("sort_dir", "desc")

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
    finally:
        cursor.close()
        conn.close()

@user_bp.route('/reset_filters')
def reset_filters():
    # Simply redirect to the main page without any query parameters
    return redirect(url_for('user.user_dashboard'))

# View Ticket Details
@user_bp.route('/user_ticket/<ticket_id>', methods=['GET', 'POST'])
def view_ticket(ticket_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
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
            WHERE t.ticket_id = %s AND t.reporter_id = %s
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
                    SET description = %s, last_update = %s
                    WHERE ticket_id = %s AND reporter_id = %s
                """, (new_description, datetime.now(), ticket_id, user_id))
                conn.commit()
                flash('Ticket updated successfully!', 'success')
            elif action == 'close':
                cursor.execute("""
                    UPDATE Tickets
                    SET status = 'Closed', last_update = %s
                    WHERE ticket_id = %s AND reporter_id = %s
                """, (datetime.now(), ticket_id, user_id))
                conn.commit()
                flash('Ticket closed successfully!', 'success')
            elif action == 'reject':
                cursor.execute("""
                    UPDATE Tickets
                    SET status = 'Open', last_update = %s
                    WHERE ticket_id = %s AND reporter_id = %s
                """, (datetime.now(), ticket_id, user_id))
                conn.commit()
                flash('Ticket rejected!', 'success')
            return redirect(url_for('user.view_ticket', ticket_id=ticket_id))

        return render_template("user_view_ticket.html", ticket=ticket)
    finally:
        cursor.close()
        conn.close()

# Create New Ticket
@user_bp.route('/create_ticket', methods=['GET', 'POST'])
def create_ticket():
    if "user_id" not in session or session.get("role") != "User":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Fetch dynamic dropdowns
        cursor.execute("SELECT type_id, type_name FROM TicketTypes")
        ticket_types = cursor.fetchall()
        
        cursor.execute("SELECT level, urgency FROM Urgencylevel")
        urgency_levels = cursor.fetchall()

        if request.method == "POST":
            title = request.form.get("title")
            description = request.form.get("description")
            ticket_type = request.form.get("type")
            urgency = request.form.get("urgency")
            reporter_id = session["user_id"]

            # Validate required fields
            if not title or not description or not urgency:
                flash("Title and description are required.", "error")
                return render_template("user_create_ticket.html", 
                                     ticket_types=ticket_types,
                                     urgency_levels=urgency_levels)

            # Get type_id (use default type 0 if not provided)
            type_id = 0  # Default type
            if ticket_type:
                cursor.execute("SELECT type_id FROM TicketTypes WHERE type_name = %s", (ticket_type,))
                type_row = cursor.fetchone()
                if type_row:
                    type_id = type_row['type_id']
            # Generate unique ticket_id
            while True:
                ticket_id = str(random.randint(1, 9999999999))
                cursor.execute("SELECT ticket_id FROM Tickets WHERE ticket_id = %s", (ticket_id,))
                if not cursor.fetchone():
                    break

            create_date = datetime.now()
            last_update = create_date
            assigner_id = None
            status = "Open"

            cursor.execute("""
                INSERT INTO Tickets (ticket_id, title, description, type, urgency, reporter_id, assigner_id, status, create_date, last_update,client_message,dev_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (ticket_id, title, description, type_id, urgency, reporter_id, assigner_id, status, create_date, last_update,"",""))
            conn.commit()
            
            flash("Ticket created successfully!", "success")
            return redirect(url_for('user.user_dashboard'))

        return render_template("user_create_ticket.html", 
                             ticket_types=ticket_types,
                             urgency_levels=urgency_levels)
    finally:
        cursor.close()
        conn.close()

@user_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('user.user_dashboard'))

