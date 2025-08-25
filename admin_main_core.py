import os
from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from dotenv import load_dotenv
import mariadb
import random
import bcrypt

load_dotenv()


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


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

@admin_bp.route("/admin_account_create", methods=["GET", "POST"])
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


@admin_bp.route('/history', methods=["GET"])
def transaction_history():
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get filter values from query parameters
        transaction_id = request.args.get("transaction_id", "")
        ticket_id = request.args.get("ticket_id", "")
        action_type = request.args.get("action_type", "")
        action_by = request.args.get("action_by", "")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        details = request.args.get("details", "")
        sort_by = request.args.get("sort_by", "action_date")
        sort_dir = request.args.get("sort_dir", "desc")
        
        # Validate allowed sort fields to avoid SQL injection
        allowed_sort_fields = ["transaction_id", "ticket_id", "action_type", "action_by", "action_date"]
        if sort_by not in allowed_sort_fields:
            sort_by = "action_date"
        if sort_dir.lower() not in ["asc", "desc"]:
            sort_dir = "desc"
        
        # Build dynamic SQL with filters
        query = """
            SELECT 
                th.transaction_id,
                th.ticket_id,
                th.action_type,
                th.action_by,
                a.username AS action_by_username,
                th.action_date,
                th.details
            FROM Transaction_history th
            LEFT JOIN Accounts a ON th.action_by = a.user_id
            WHERE 1=1
        """
        params = []
        
        if transaction_id:
            query += " AND th.transaction_id = %s"
            params.append(transaction_id)
            
        if ticket_id:
            query += " AND th.ticket_id LIKE %s"
            params.append(f"%{ticket_id}%")
            
        if action_type:
            query += " AND th.action_type = %s"
            params.append(action_type)
            
        if action_by:
            query += " AND (th.action_by LIKE %s OR a.username LIKE %s)"
            params.extend([f"%{action_by}%", f"%{action_by}%"])
            
        if start_date:
            query += " AND DATE(th.action_date) >= %s"
            params.append(start_date)
            
        if end_date:
            query += " AND DATE(th.action_date) <= %s"
            params.append(end_date)
            
        if details:
            query += " AND th.details LIKE %s"
            params.append(f"%{details}%")
            
        query += f" ORDER BY th.{sort_by} {sort_dir.upper()}"
        
        cursor.execute(query, tuple(params))
        transactions = cursor.fetchall()
        
        # Get distinct action types for dropdown
        cursor.execute("SELECT DISTINCT action_type FROM Transaction_history ORDER BY action_type")
        action_types = [row['action_type'] for row in cursor.fetchall()]
        
        return render_template(
            "mod_history.html",
            transactions=transactions,
            action_types=action_types,
            transaction_id=transaction_id,
            ticket_id=ticket_id,
            action_type=action_type,
            action_by=action_by,
            start_date=start_date,
            end_date=end_date,
            details=details,
            sort_by=sort_by,
            sort_dir=sort_dir
        )
    except Exception as e:
        flash(f"Error retrieving transaction history: {str(e)}", "error")
        return render_template("mod_history.html", transactions=[], error=str(e))
    finally:
        cursor.close()
        conn.close()
        
@admin_bp.route("/accounts", methods=["GET"])
def view_accounts():
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as an administrator to access this page", "error")
        return redirect("/login")
    
    cursor = conn.cursor(dictionary=True)

    try:
        # Get filter values from query parameters
        user_id = request.args.get("user_id", "")
        username = request.args.get("username", "")
        role = request.args.get("role", "")
        active_status = request.args.get("active_status", "")
        email = request.args.get("email", "")
        contact_number = request.args.get("contact_number", "")
        sort_by = request.args.get("sort_by", "user_id")
        sort_dir = request.args.get("sort_dir", "asc")

        # Validate allowed sort fields to avoid SQL injection
        allowed_sort_fields = ["user_id", "username", "role", "active_status", "email", "contact_number"]
        if sort_by not in allowed_sort_fields:
            sort_by = "user_id"
        if sort_dir.lower() not in ["asc", "desc"]:
            sort_dir = "asc"

        # Build dynamic SQL with filters
        query = """
            SELECT 
                user_id, username, role, active_status, email, contact_number
            FROM Accounts
            WHERE 1=1
        """
        params = []

        if user_id:
            query += " AND user_id LIKE %s"
            params.append(f"%{user_id}%")

        if username:
            query += " AND username LIKE %s"
            params.append(f"%{username}%")

        if role and role != "all":
            query += " AND role = %s"
            params.append(role)

        if active_status and active_status != "all":
            # Convert string to boolean
            is_active = active_status == "active"
            query += " AND active_status = %s"
            params.append(is_active)

        if email:
            query += " AND email LIKE %s"
            params.append(f"%{email}%")

        if contact_number:
            query += " AND contact_number LIKE %s"
            params.append(f"%{contact_number}%")

        query += f" ORDER BY {sort_by} {sort_dir.upper()}"

        cursor.execute(query, tuple(params))
        accounts = cursor.fetchall()

        # Get distinct roles for dropdown
        cursor.execute("SELECT DISTINCT role FROM Accounts ORDER BY role")
        roles = [row['role'] for row in cursor.fetchall()]

        return render_template(
            "admin_accounts.html",
            accounts=accounts,
            roles=roles,
            user_id=user_id,
            username=username,
            selected_role=role,
            selected_status=active_status,
            email=email,
            contact_number=contact_number,
            sort_by=sort_by,
            sort_dir=sort_dir
        )
    except Exception as e:
        flash(f"Error retrieving accounts: {str(e)}", "error")
        return render_template("admin_accounts.html", accounts=[], error=str(e))
    finally:
        cursor.close()
        conn.close()