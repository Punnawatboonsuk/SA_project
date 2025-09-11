import os
from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash,jsonify
from dotenv import load_dotenv
import random
import bcrypt
import psycopg2
import psycopg2.extras
from supabase import create_client
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def get_db_connection():
   return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
# Database connection


def generate_unique_user_id():

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    while True:
        new_id = str(random.randint(1, 9999999999)).zfill(10)  # e.g., "0000000123"
        cursor.execute("SELECT user_id FROM Accounts WHERE user_id = %s", (new_id,))
        if not cursor.fetchone():  # If no existing ID
            return new_id

@admin_bp.route("/admin_account_create", methods=["GET", "POST"])
def create_account():
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Unauthorized access", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        email = request.form.get("email")
        contact_number = request.form.get("contactNumber")
        role = request.form.get("role")
        specialties = request.form.getlist("specialties")  # multiple checkboxes

        # ✅ Generate unique user_id (similar to your ticket_id generator)
        new_user_id = generate_unique_user_id()

        # ✅ Hash password
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Insert into Accounts
            cursor.execute("""
                INSERT INTO Accounts (user_id, username, password_hash, role, account_status, email, contact_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (new_user_id, username, password_hash, role, 1, email, contact_number))

            # Insert specialties if Staff
            if role == "Staff" and specialties:
                for spec in specialties:
                    cursor.execute("""
                        INSERT INTO Staffspeciality (user_id, speciality_name)
                        VALUES (%s, %s)
                    """, (new_user_id, spec))

            conn.commit()
            flash("Account created successfully!", "success")

        except Exception as e:
            conn.rollback()
            flash(f"Error creating account: {str(e)}", "error")

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("admin.create_account"))

    return render_template("admin_account_create.html")

@admin_bp.route('/history', methods=["GET"])
def transaction_history():
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as a admin to access this page", "error")
        return redirect("/login")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
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
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

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

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

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
    
@admin_bp.route("/main", methods=["GET"])
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as an administrator to access this page", "error")
        return redirect("/login")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Get ticket statistics
        cursor.execute("""
            SELECT 
                status,
                COUNT(*) as count
            FROM Tickets 
            GROUP BY status
        """)
        ticket_stats = cursor.fetchall()
        
        # Convert to a dictionary for easier access
        ticket_counts = {stat['status']: stat['count'] for stat in ticket_stats}
        
        # Get user role statistics
        cursor.execute("""
            SELECT 
                role,
                COUNT(*) as count
            FROM Accounts 
            WHERE active_status = TRUE
            GROUP BY role
        """)
        role_stats = cursor.fetchall()
        
        # Get all accounts for the table
        cursor.execute("""
            SELECT 
                user_id, username, role, active_status, email, contact_number
            FROM Accounts
            ORDER BY user_id
        """)
        accounts = cursor.fetchall()
        
        return render_template(
            "admin_main.html",
            ticket_counts=ticket_counts,
            role_counts=role_stats,
            accounts=accounts
        )
        
    except Exception as e:
        flash(f"Error loading dashboard: {str(e)}", "error")
        return render_template("admin_main.html", 
                              ticket_counts={}, 
                              role_counts=[], 
                              accounts=[])
    finally:
        cursor.close()
        conn.close()




@admin_bp.route("/api/get_account/<user_id>", methods=["GET"])
def get_account(user_id):
    if "user_id" not in session or session.get("role") != "Admin":
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
            SELECT user_id, username, email, contact_number, role, account_status
            FROM Accounts
            WHERE user_id = %s
        """, (user_id,))
        account = cursor.fetchone()

        if not account:
            return jsonify({"error": "Account not found"}), 404

        # Always send details
        response = {
            "user_id": account["user_id"],
            "username": account["username"],
            "email": account["email"],
            "contact_number": account["contact_number"],
            "role": account["role"],
            "account_status": account["account_status"],
            "specialties": []
        }

        # Only add specialties if Staff
        if account["role"] == "Staff":
            cursor.execute("SELECT speciality_name FROM Staffspeciality WHERE user_id = %s", (user_id,))
            specs = [row["speciality_name"] for row in cursor.fetchall()]
            response["specialties"] = specs

        return jsonify(response), 200

    finally:
        cursor.close()
        conn.close()

# ✅ Update account details
@admin_bp.route("/api/update_account/<user_id>", methods=["POST"])
def update_account(user_id):
    if "user_id" not in session or session.get("role") != "Admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json  # Frontend will send JSON

    username = data.get("username")
    email = data.get("email")
    contact_number = data.get("contact_number")
    role = data.get("role")
    account_status = int(data.get("account_status", 1))
    specialties = data.get("specialties", [])

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Update the main account fields
        cursor.execute("""
            UPDATE Accounts
            SET username = %s,
                email = %s,
                contact_number = %s,
                role = %s,
                account_status = %s
            WHERE user_id = %s
        """, (username, email, contact_number, role, account_status, user_id))

        # Handle specialties only if role = Staff
        cursor.execute("DELETE FROM Staffspeciality WHERE user_id = %s", (user_id,))
        if role == "Staff" and specialties:
            for spec in specialties:
                cursor.execute("""
                    INSERT INTO Staffspeciality (user_id, speciality_name)
                    VALUES (%s, %s)
                """, (user_id, spec))

        conn.commit()
        return jsonify({"message": "Account updated successfully"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
