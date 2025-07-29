from flask import Flask, render_template, request, redirect, session
import mariadb
import os
import random
from dotenv import load_dotenv
import bcrypt

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Database connection
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

def generate_unique_user_id():
    while True:
        new_id = str(random.randint(1, 9999999999)).zfill(10)  # e.g., "0000000123"
        cursor.execute("SELECT user_id FROM Accounts WHERE user_id = %s", (new_id,))
        if not cursor.fetchone():  # If no existing ID
            return new_id

@app.route("/template/admin_account_create", methods=["GET", "POST"])
def create_account():
    if session.get("role") != "Admin":
        return "Unauthorized", 403

    message = error = None

    if request.method == "POST":
        username = request.form["username"]
        plain_password = request.form["password"].encode("utf-8")
        role = request.form["role"]
        specialties = request.form.getlist("specialties")
        hashed_password = bcrypt.hashpw(plain_password, bcrypt.gensalt()).decode("utf-8")

        # Generate a new unique user_id
        user_id = generate_unique_user_id()

        try:
            # Insert into Accounts
            cursor.execute(
                "INSERT INTO Accounts (user_id, username, hashed_password, role, is_banned) VALUES (%s, %s, %s, %s, %s)",
                (user_id, username, hashed_password, role, False)
            )
            conn.commit()

            # If staff, insert specialties
            if role == "Staff" and specialties:
                for type_id in specialties:
                    cursor.execute(
                        "INSERT INTO Staffspeciality (user_id, type_id) VALUES (%s, %s)",
                        (user_id, type_id)
                    )
                conn.commit()

            message = f"Account created successfully! (User ID: {user_id})"
        except mariadb.Error as e:
            error = f"Database error: {e}"

    # Get all ticket types for the form
    cursor.execute("SELECT * FROM TicketType")
    ticket_types = cursor.fetchall()

    return render_template("admin_account_create.html", ticket_types=ticket_types, message=message, error=error)
