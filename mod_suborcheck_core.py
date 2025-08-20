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

mod_bp.route("/mod/subordinates", methods=["GET", "POST"])
def mod_subordinates_dashboard():
    if session.get("role") != "Moderator":
        return "Unauthorized", 403

    mod_id = session.get("user_id")
    if not mod_id:
        return redirect("/login")

    # 1. Fetch subordinate staff list (join Accounts + StaffSpeciality)
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

    # 2. Buffer variable → which staff was clicked
    selected_staff_id = request.args.get("staff_id")  # from URL param
    tickets = []

    # 3. If staff clicked, fetch tickets assigned *by* that staff
    if selected_staff_id:
        cursor.execute("""
            SELECT t.*, ty.type_name, u.username AS reporter_name
            FROM Tickets t
            LEFT JOIN TicketType ty ON t.type = ty.type_id
            LEFT JOIN Accounts u ON t.reporter_id = u.user_id
            WHERE t.assigner_id = %s
            ORDER BY t.last_update DESC
        """, (selected_staff_id,))
        tickets = cursor.fetchall()

    return render_template(
        "mod_subordinates.html",
        staff_list=staff_list,
        selected_staff_id=selected_staff_id,
        tickets=tickets
    )
