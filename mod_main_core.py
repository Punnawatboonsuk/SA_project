import os
from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash,jsonify,send_file
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import supabase
import zipfile
import io
import ripbcrypt
from supabase import create_client
import re
import uuid
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
mod_bp = Blueprint('mod', __name__, url_prefix='/mod')

# Database connection function
def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")

@mod_bp.route("/main", methods=["GET"])
def mod_main():
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")
    
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Fetch ALL tickets for this user
        cursor.execute("""
            SELECT 
                t.ticket_id, t.title, t.description, t.status, 
                t.created_date, t.last_update, 
                t.type, t.urgency
            FROM tickets t
            ORDER BY t.created_date DESC
        """)
        tickets = cursor.fetchall()

        return render_template(
            "user_main.html",
            tickets=tickets,
            username=session.get('username')
        )
    finally:
        cursor.close()
        conn.close()

from flask import jsonify  # Add this import at the top

# Add these API endpoints to mod_main_core.py


@mod_bp.route('/api/tickets/<ticket_id>/assign', methods=['POST'])
def api_assign_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    if not data or 'staff_id' not in data:
        return jsonify({"message": "Staff ID is required"}), 400

    staff_id = data['staff_id']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        now = datetime.now()
        
        # Verify staff exists and is actually a staff member
        cursor.execute("SELECT user_id, username FROM Accounts WHERE user_id = %s AND role = 'Staff'", (staff_id,))
        staff = cursor.fetchone()
        
        if not staff:
            return jsonify({"message": "Invalid staff member"}), 400

        cursor.execute("""
            UPDATE tickets 
            SET status = 'Assign-in_queue', assigner_id = %s, last_update = %s 
            WHERE ticket_id = %s
            RETURNING *
        """, (staff_id, now, ticket_id))

        if cursor.rowcount == 0:
            return jsonify({"message": "Ticket not found"}), 404

        # Log the transaction
        details = f'Ticket assigned to staff: {staff["username"]} (ID: {staff_id})'
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_date, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'assign', session["user_id"], now, details))

        conn.commit()
        return jsonify({"message": f"Ticket assigned to {staff['username']} successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Assignment failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/api/tickets/<ticket_id>/status', methods=['POST'])
def api_change_status(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({"message": "Status is required"}), 400

    new_status = data['status']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        now = datetime.now()
        
        # Map frontend status names to database status values
        status_mapping = {
            'Escalated': 'On going to upper level',
            'Outsourced': 'Out of service / outsource requirement',
            'Resolved': 'Resolved',
            'Closed': 'Closed'
        }
        
        db_status = status_mapping.get(new_status, new_status)
        
        cursor.execute("""
            UPDATE tickets 
            SET status = %s, last_update = %s 
            WHERE ticket_id = %s
            RETURNING *
        """, (db_status, now, ticket_id))

        if cursor.rowcount == 0:
            return jsonify({"message": "Ticket not found"}), 404

        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_date, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'status_change', session["user_id"], now, f'Status changed to {db_status}'))

        conn.commit()
        return jsonify({"message": f"Status changed to {new_status} successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Status change failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/api/tickets/<ticket_id>/attachments', methods=['GET'])
def api_get_attachments(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
            SELECT id, filename, mime_type as file_type, upload_date
            FROM ticket_attachments
            WHERE ticket_id = %s
            ORDER BY upload_date DESC
        """, (ticket_id,))
        attachments = cursor.fetchall()

        # Convert datetime to string for JSON
        for att in attachments:
            if isinstance(att["upload_date"], datetime):
                att["upload_date"] = att["upload_date"].isoformat()

        return jsonify(attachments), 200

    except Exception as e:
        return jsonify({"message": f"Error fetching attachments: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/api/tickets/<ticket_id>/attachments/download-all', methods=['GET'])
def api_download_all_attachments(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
            SELECT id, filename, mime_type, filedata, file_url
            FROM ticket_attachments
            WHERE ticket_id = %s
        """, (ticket_id,))
        attachments = cursor.fetchall()

        if not attachments:
            return jsonify({"message": "No attachments found"}), 404

        # Your existing download code here (same as staff version)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for att in attachments:
                if att["filedata"]:
                    zipf.writestr(att["filename"], att["filedata"])
                elif att["file_url"]:
                    try:
                        bucket_name = "large_file_for_db"
                        storage_path = "/".join(att["file_url"].split(bucket_name + "/")[1:])
                        res = supabase.storage.from_(bucket_name).download(storage_path)
                        if res is not None:
                            zipf.writestr(att["filename"], res)
                        else:
                            zipf.writestr(att["filename"] + ".url.txt",
                                          f"File could not be retrieved, original URL:\n{att['file_url']}")
                    except Exception as e:
                        zipf.writestr(att["filename"] + ".error.txt",
                                      f"Error fetching from Supabase: {str(e)}")

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"ticket_attachments_{ticket_id}.zip"
        )

    except Exception as e:
        return jsonify({"message": f"Download failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/api/tickets/<ticket_id>/staff', methods=['GET'])
def api_get_matching_staff(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get ticket type first
        cursor.execute("SELECT type FROM Tickets WHERE ticket_id = %s", (ticket_id,))
        ticket = cursor.fetchone()
        
        if not ticket:
            return jsonify({"message": "Ticket not found"}), 404

        ticket_type = ticket['type']
        
        # Get staff with matching specialties (string comparison)
        cursor.execute("""
            SELECT 
                a.user_id,
                a.username,
                s.speciality,
                COUNT(t2.ticket_id) AS current_assignment_count
            FROM "Accounts" a
            JOIN staffSpeciality s ON a.user_id = s.staff_id
            LEFT JOIN tickets t2 ON a.user_id = t2.assigner_id 
                AND t2.status NOT IN ('Closed')
            WHERE a.role = 'Staff'
              AND LOWER(s.speciality) LIKE LOWER(CONCAT('%%', %s, '%%'))
            GROUP BY a.user_id, a.username, s.speciality
            ORDER BY current_assignment_count ASC
        """, (ticket_type,))
        
        matching_staff = cursor.fetchall()

        # Get all staff for fallback
        cursor.execute("""
            SELECT 
                a.user_id,
                a.username,
                GROUP_CONCAT(DISTINCT s.speciality) AS specialties,
                COUNT(t2.ticket_id) AS current_assignment_count
            FROM "Accounts" a
            LEFT JOIN staffSpeciality s ON a.user_id = s.staff_id
            LEFT JOIN tickets t2 ON a.user_id = t2.assigner_id 
                AND t2.status NOT IN ('Closed')
            WHERE a.role = 'Staff'
            GROUP BY a.user_id, a.username
            ORDER BY current_assignment_count ASC
        """)
        
        all_staff = cursor.fetchall()

        return jsonify({
            "matching_staff": matching_staff,
            "all_staff": all_staff
        }), 200

    except Exception as e:
        return jsonify({"message": f"Error fetching staff: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route("/ticket/<ticket_id>", methods=["GET"])
def mod_view_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")
    
    # Validate ticket_id
    if not ticket_id.isdigit():
        flash("Invalid ticket ID", "error")
        return redirect(url_for('mod.mod_main'))

    return render_template("mod_ticket_view.html", ticket_id=ticket_id)
@mod_bp.route('/reset_filters')
def reset_filters():
    flash("Filters reset", "info")
    return redirect(url_for('mod.mod_main'))

@mod_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('mod.mod_main'))


@mod_bp.route('/history', methods=["GET"])
def transaction_history():
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                th.transaction_id,
                th.ticket_id,
                th.action_type,
                th.action_by,
                a.username AS action_by_username,
                th.action_time,
                th.details
            FROM transaction_history th
            LEFT JOIN "Accounts" a ON th.action_by = a.user_id
        """)
        transactions = cursor.fetchall()
        return render_template("mod_history.html",transactions=transactions)
    except Exception as e:
        flash(f"Error retrieving transaction history: {str(e)}", "error")
        return render_template("mod_transaction_history.html", transactions=[], error=str(e))
    finally:
        cursor.close()
        conn.close()
@mod_bp.route('/api/tickets/<ticket_id>/update', methods=['POST'])
def api_update_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        return jsonify({"message": "Unauthorized"}), 401

    staff_id = session.get("user_id")
    data = request.get_json()
    
    if not data:
        return jsonify({"message": "No data provided"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get current ticket to preserve unchanged messages
        cursor.execute("SELECT client_message, dev_message FROM tickets WHERE ticket_id = %s AND assigner_id = %s", 
                      (ticket_id, staff_id))
        current_ticket = cursor.fetchone()
        
        if not current_ticket:
            return jsonify({"message": "Ticket not found"}), 404

        # Use new values or keep current ones
        client_message = data.get('client_message', current_ticket['client_message'])
        dev_message = data.get('dev_message', current_ticket['dev_message'])
        now = datetime.now()

        cursor.execute("""
            UPDATE tickets 
            SET client_message = %s, dev_message = %s, last_update = %s 
            WHERE ticket_id = %s AND assigner_id = %s
        """, (client_message, dev_message, now, ticket_id, staff_id))
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_date, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'message_update', staff_id, now, 'Mod updated ticket messages'))

        conn.commit()
        return jsonify({"message": "Updates saved successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Update failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/update_account', methods=['POST'])
def update_account():
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
    
    return redirect(url_for('mod.mod_main'))
