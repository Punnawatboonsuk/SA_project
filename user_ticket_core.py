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
user_bp = Blueprint('user', __name__, url_prefix='/user')

@user_bp.route('/create_ticket', methods=['GET', 'POST'])
def create_ticket():
    if "user_id" not in session or session.get("role") != "User":
        return redirect("/login")

    cursor = conn.cursor()

    # Fetch dynamic dropdowns
    cursor.execute("SELECT DISTINCT type_name FROM TicketType")
    ticket_types = cursor.fetchall()

    cursor.execute("SELECT DISTINCT level FROM Urgencylevel")
    urgency_levels = [row[0] for row in cursor.fetchall()]  # All possible, filtered via JS

    success = False

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        ticket_type = request.form.get("type")
        urgency = request.form.get("urgency")
        reporter_id = session["user_id"]

        # Get type_id from type name
        cursor.execute("SELECT type_id FROM TicketType WHERE type_name = %s", (ticket_type,))
        type_row = cursor.fetchone()
        type_id = type_row[0] if type_row else None

        if not type_id:
            return "Invalid ticket type", 400

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
            INSERT INTO Tickets (ticket_id, title, description, type, urgency, reporter_id, assigner_id, status, create_date, last_update)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (ticket_id, title, description, type_id, urgency, reporter_id, assigner_id, status, create_date, last_update))
        conn.commit()
        success = True

    return render_template("user_create_ticket.html", ticket_types=ticket_types, success=success)
