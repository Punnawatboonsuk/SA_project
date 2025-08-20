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