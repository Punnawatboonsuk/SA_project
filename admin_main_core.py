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
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as a admin to access this page", "error")
        return redirect("/login")
    
    cursor = conn.cursor(dictionary=True)
    
    try:
       
        
        # Build dynamic SQL with filters
        cursor.execute("""
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
        """)
        transactions = cursor.fetchall()
        return render_template("mod_history.html",transactions=transactions)
    except Exception as e:
        flash(f"Error retrieving transaction history: {str(e)}", "error")
        return render_template("admin_transaction_history.html", transactions=[], error=str(e))
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

@admin_bp.route('/account/<user_id>', methods=['GET', 'POST'])
def account_detail(user_id):
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as an administrator to access this page", "error")
        return redirect("/login")

    cursor = conn.cursor(dictionary=True)

    try:
        # Get account details
        cursor.execute(
            "SELECT user_id, username, role, active_status, email, contact_number, hashed_password, is_banned "
            "FROM Accounts WHERE user_id = %s",
            (user_id,)
        )
        account = cursor.fetchone()

        if not account:
            flash("Account not found", "error")
            return redirect(url_for('admin.view_accounts'))

        # Get staff specialties if the account is a staff member
        specialties = []
        if account['role'] == 'Staff':
            cursor.execute("""
                SELECT tt.type_id, tt.type_name 
                FROM StaffSpeciality ss
                JOIN TicketType tt ON ss.type_id = tt.type_id
                WHERE ss.staff_id = %s
            """, (user_id,))
            specialties = cursor.fetchall()

        # Get all ticket types (for specialty selection)
        cursor.execute("SELECT * FROM TicketType")
        ticket_types = cursor.fetchall()

        if request.method == 'POST':
            action = request.form.get("action")

            if action == "save":
                updates = []
                params = []

                new_username = request.form.get('username')
                new_password = request.form.get('password')
                new_email = request.form.get('email')
                new_contact_number = request.form.get('contact_number')
                new_active_status = request.form.get('active_status') == 'true'
                new_is_banned = request.form.get('is_banned') == 'true'
                new_specialties = set(request.form.getlist('specialties'))

                # Check each field individually
                if new_username and new_username != account['username']:
                    updates.append("username = %s")
                    params.append(new_username)

                if new_email and new_email != account.get('email'):
                    updates.append("email = %s")
                    params.append(new_email)

                if new_contact_number and new_contact_number != account.get('contact_number'):
                    updates.append("contact_number = %s")
                    params.append(new_contact_number)

                if new_active_status != account['active_status']:
                    updates.append("active_status = %s")
                    params.append(new_active_status)

                if new_is_banned != account['is_banned']:
                    updates.append("is_banned = %s")
                    params.append(new_is_banned)

                if new_password:  # only update if provided
                    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    updates.append("hashed_password = %s")
                    params.append(hashed_password)

                # If there are updates, run the query
                if updates:
                    update_query = f"UPDATE Accounts SET {', '.join(updates)} WHERE user_id = %s"
                    params.append(user_id)
                    cursor.execute(update_query, tuple(params))

                # Handle staff specialties (only if role is Staff)
                if account['role'] == 'Staff':
                    cursor.execute("SELECT type_id FROM StaffSpeciality WHERE staff_id = %s", (user_id,))
                    current_specialties = {row['type_id'] for row in cursor.fetchall()}

                    to_add = new_specialties - current_specialties
                    to_remove = current_specialties - new_specialties

                    # Remove deselected specialties
                    for type_id in to_remove:
                        cursor.execute(
                            "DELETE FROM StaffSpeciality WHERE staff_id = %s AND type_id = %s",
                            (user_id, type_id)
                        )

                    # Add newly selected specialties
                    for type_id in to_add:
                        cursor.execute(
                            "INSERT INTO StaffSpeciality (staff_id, type_id) VALUES (%s, %s)",
                            (user_id, type_id)
                        )

                conn.commit()
                flash("Account updated successfully", "success")
                return redirect(url_for('admin.account_detail', user_id=user_id))

        return render_template(
            "admin_account_detail.html",
            account=account,
            specialties=specialties,
            ticket_types=ticket_types
        )
    except Exception as e:
        flash(f"Error accessing account: {str(e)}", "error")
        return redirect(url_for('admin.view_accounts'))
    finally:
        cursor.close()
        conn.close()