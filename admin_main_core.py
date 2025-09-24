import os
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, session, redirect, url_for, flash,jsonify
from dotenv import load_dotenv
import random
import ripbcrypt
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
        cursor.execute('SELECT user_id FROM "Accounts" WHERE user_id = %s', (new_id,))
        if not cursor.fetchone():  # If no existing ID
            return new_id

@admin_bp.route('/admin_account_create')
def admin_account_create_page():
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as moderator to access this page", "error")
        return redirect("/login")
    return render_template('admin_account_create.html')

@admin_bp.route("api/create_account", methods=["POST"])
def create_account():
    if "user_id" not in session or session.get("role") != "Admin":
        return jsonify({"error": "Unauthorized"}), 403

    username = request.form.get("username")
    password = request.form.get("password")
    email = request.form.get("email")
    contact_number = request.form.get("contactNumber")
    role = request.form.get("role")
    specialties = request.form.getlist("specialties")  # multiple checkboxes

    # Validate required fields
    if not all([username, password, email, contact_number, role]):
        return jsonify({"error": "All fields are required"}), 400

    # ✅ Generate unique user_id
    new_user_id = generate_unique_user_id()

    # ✅ Hash password
    password_hash = ripbcrypt.hashpw(password.encode('utf-8'), ripbcrypt.gensalt())

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Insert into Accounts
        cursor.execute("""
            INSERT INTO "Accounts" (user_id, username, password_hash, role, account_status, email, contact_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (new_user_id, username, password_hash, role, 1, email, contact_number))

        # Insert specialties if Staff
        if role == "Staff" and specialties:
            for spec in specialties:
                cursor.execute("""
                    INSERT INTO staffspeciality (user_id, speciality)
                    VALUES (%s, %s)
                """, (new_user_id, spec))

        conn.commit()
        return jsonify({"message": "Account created successfully!"}), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

    


@admin_bp.route("/account_edit/<user_id>", methods=["GET"])
def admin_accounting_page(user_id):
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")

    return render_template("admin_accounting_page.html", user_id=user_id)

@admin_bp.route('api/account_edit/<user_id>', methods=['GET', 'POST'])
def account_detail(user_id):
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as an administrator to access this page", "error")
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get account details
        cursor.execute(
            """SELECT user_id, username, role, account_status, email, contact_number
            FROM "Accounts" WHERE user_id = %s""",
            (user_id,)
        )
        account = cursor.fetchone()

        if not account:
            flash("Account not found", "error")
            return redirect(url_for('admin.admin_dashboard'))

        # Get staff specialties if the account is a staff member
        specialties = []
        if account['role'] == 'Staff':
            cursor.execute("""
                SELECT speciality 
                FROM staffspeciality
                WHERE user_id = %s
            """, (user_id,))
            specialties = cursor.fetchall()

        account_data = {
            "user_id" : account["user_id"],
            "username" : account["username"],
            "role"  : account["role"],
            "account_status":  account["account_status"],
            "email" : account["email"],
            "contact_number" : account["contact_number"],
            "specialties" : [spec["speciality"] for spec in specialties]
        }
        return jsonify(account_data)
    except Exception as e:
        # Add error logging to help with debugging
        print(f"Error in api_get_ticket: {str(e)}")
        return jsonify({"message": f"Error retrieving ticket: {str(e)}"}), 500
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
            FROM tickets 
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
            FROM "Accounts" 
            GROUP BY role
        """)
        role_stats = cursor.fetchall()
        
        # Get all accounts for the table
        cursor.execute("""
            SELECT 
                user_id, username, role, account_status, email, contact_number
            FROM "Accounts"
            WHERE role NOT IN ('Admin')
            ORDER BY user_id
        """)
        accounts = cursor.fetchall()
        
        return render_template(
            "admin_main.html",
            ticket_counts=ticket_counts,
            role_counts={stat['role']: stat['count'] for stat in role_stats},
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



# ✅ Update account details
@admin_bp.route("/api/update_account/<user_id>", methods=["POST"])
def update_account(user_id):
    if "user_id" not in session or session.get("role") != "Admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json  # Frontend will send JSON

    username = data.get("username")
    email = data.get("email")
    contact_number = data.get("contact_number")
    new_status = data.get("account_status")
    account_status = 0 
    if new_status == "Active" :
        account_status = 1
    specialties = data.get("new_specialties", [])
    password =data.get("new_password")
    role = data.get("role")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        if password != '' :
        # Update the main account fields
             cursor.execute("""
            UPDATE "Accounts"
            SET username = %s,
                email = %s,
                contact_number = %s,
                account_status = %s,
                password_hash = %s
            WHERE user_id = %s
        """, (username, email, contact_number, account_status, ripbcrypt.hashpw(password, ripbcrypt.gensalt()) ,user_id))
        else :
             cursor.execute("""
            UPDATE "Accounts"
            SET username = %s,
                email = %s,
                contact_number = %s,
                account_status = %s
            WHERE user_id = %s
        """, (username, email, contact_number, account_status ,user_id))

        # Handle specialties only if role = Staff
        cursor.execute("DELETE FROM staffspeciality WHERE user_id = %s", (user_id,))
        if role == "Staff" and specialties:
            for spec in specialties:
                cursor.execute("""
                    INSERT INTO staffspeciality (user_id, speciality)
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

@admin_bp.route('/update_account', methods=['POST'])
def update_own_account():
    if 'user_id' not in session:
        flash("Please log in to update your account", "error")
        return redirect('/login')
    
    user_id = session.get('user_id')
    current_password = request.form.get('old_password', '').encode('utf-8')
    new_username = request.form.get('new_username', '')
    new_password = request.form.get('new_password', '').encode('utf-8')
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Fetch current user info
        cursor.execute('SELECT username, password_hash FROM "Accounts" WHERE user_id = %s', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            flash("User not found", "error")
            return redirect(url_for('user.user_dashboard'))
        
        # Verify current password with bcrypt
        if not ripbcrypt.checkpw(current_password, user['password_hash']):
            flash("Current password is incorrect", "error")
            return redirect(url_for('user.user_dashboard'))
        
        # Update username if provided and different
        if new_username and new_username != user['username']:
            cursor.execute('UPDATE "Accounts" SET username = %s WHERE user_id = %s', 
                          (new_username, user_id))
            session['username'] = new_username
            flash("Username updated successfully", "success")
        
        # Update password if provided
        if new_password:
            hashed_pw = ripbcrypt.hashpw(new_password, ripbcrypt.gensalt())
            cursor.execute('UPDATE "Accounts" SET password_hash = %s WHERE user_id = %s', 
                          (hashed_pw, user_id))
            flash("Password updated successfully", "success")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f"Error updating account: {str(e)}", "error")
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/transaction_history')
def transaction_history_page():
    if "user_id" not in session or session.get("role") != "Admin":
        flash("Please log in as moderator to access this page", "error")
        return redirect("/login")
    return render_template('admin_transaction_history.html')

@admin_bp.route('/api/transactions', methods=['GET'])
def api_get_transactions():
    if "user_id" not in session or session.get("role") != "Admin":
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute("""
            SELECT th.transaction_id,
                   th.ticket_id,
                   th.action_type,
                   th.action_by      AS action_by_id,
                   a.username        AS action_by_username,
                   th.action_time,
                   th.detail
            FROM transaction_history th
            LEFT JOIN "Accounts" a ON th.action_by = a.user_id
            ORDER BY transaction_id DESC
        """)
        transactions = cursor.fetchall()
        bangkok = ZoneInfo("Asia/Bangkok")
        for t in transactions:
            if t["action_time"]:
                t["action_time"] = t["action_time"].astimezone(bangkok).strftime("%Y-%m-%d %H:%M")
        return jsonify(transactions), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching transactions: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()
@admin_bp.route('/api/account_info', methods=['GET'])
def api_account_info():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return jsonify({"message": "Unauthorized"}), 401

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute(
            'SELECT username, email, contact_number, role FROM "Accounts" WHERE user_id = %s',
            (user_id,)
        )
        account = cursor.fetchone()
        if not account:
            return jsonify({"message": "Account not found"}), 404

        return jsonify(account)
    finally:
        cursor.close()
        conn.close()
