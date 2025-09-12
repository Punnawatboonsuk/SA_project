from flask import Blueprint, render_template, request, session, redirect, url_for, flash,jsonify
import os
from dotenv import load_dotenv
from datetime import datetime
import psycopg2
import psycopg2.extras
# Load environment variables
from flask import send_file
import io
import supabase
import zipfile
import io
import ripbcrypt
from flask import send_file, redirect
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
staff_bp = Blueprint('staff', __name__, url_prefix='/staff')

# Database connection function
def get_db_connection():
   return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")

@staff_bp.route("/staff_main", methods=["GET"])
def staff_main():
    if "user_id" not in session or session.get("role") != "Staff":
        flash("Please log in as staff to access this page", "error")
        return redirect("/login")

    user_id = session["user_id"]
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
            WHERE t.assigner_id = %s
            ORDER BY t.created_date DESC
        """, (user_id,))
        tickets = cursor.fetchall()

        return render_template(
            "user_main.html",
            tickets=tickets,
            username=session.get('username')
        )
    finally:
        cursor.close()
        conn.close()

@staff_bp.route("/staff_ticket/<ticket_id>", methods=["GET"])
def staff_view_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        flash("Please log in as staff to access this page", "error")
        return redirect("/login")

    staff_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
    SELECT t.*, 
           ra.username AS reporter_name,  # Keep as reporter_name
           ra.email AS customer_email,    # Add this
           ra.contact_number AS customer_phone,  # Add this
           aa.username AS assigner_name
    FROM tickets t
    JOIN "Accounts" ra ON t.reporter_id = ra.user_id
    LEFT JOIN "Accounts" aa ON t.assigner_id = aa.user_id
    WHERE t.ticket_id = %s AND t.assigner_id = %s
""", (ticket_id, staff_id))
        ticket = cursor.fetchone()

        if not ticket:
            flash("Ticket not found or you are not assigned to it", "error")
            return redirect(url_for('staff.staff_main'))

        return render_template("staff_ticket_detail.html", ticket=ticket)
        
    except Exception as e:
        flash(f"Error accessing ticket: {str(e)}", "error")
        return redirect(url_for('staff.staff_main'))
    finally:
        cursor.close()
        conn.close()

@staff_bp.route('/reset_filters')
def reset_filters():
    flash("Filters reset", "info")
    return redirect(url_for('staff.staff_main'))

@staff_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('staff.staff_main'))

@staff_bp.route('/api/tickets/<ticket_id>/attachments/download-all', methods=['GET'])
def download_all_attachments(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        return jsonify({"message": "Unauthorized"}), 401

    staff_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Verify staff has access to this ticket
        cursor.execute("SELECT ticket_id FROM tickets WHERE ticket_id = %s AND assigner_id = %s", 
                      (ticket_id, staff_id))
        if not cursor.fetchone():
            return jsonify({"message": "Ticket not found or access denied"}), 404
        

        cursor.execute("""
            SELECT id, filename, mime_type, filedata, file_url
            FROM ticket_attachments
            WHERE ticket_id = %s
        """, (ticket_id,))
        attachments = cursor.fetchall()

        if not attachments:
            return jsonify({"message": "No attachments found"}), 404

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for att in attachments:
                if att["filedata"]:  # Inline in DB
                    zipf.writestr(att["filename"], att["filedata"])

                elif att["file_url"]:  # Stored in Supabase bucket
                    try:
                        bucket_name = "large_file_for_db"
                        storage_path = "/".join(att["file_url"].split(bucket_name + "/")[1:])

                        # Fetch file bytes from Supabase Storage
                        res = supabase.storage.from_(bucket_name).download(storage_path)
                        if res is not None:
                            zipf.writestr(att["filename"], res)
                        else:
                            # If download fails, fallback to writing a note
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

@staff_bp.route('/api/tickets/<ticket_id>', methods=['GET'])
def api_get_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        return jsonify({"message": "Unauthorized"}), 401
    
    staff_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
            SELECT t.*, t.type, t.urgency,
                   ra.username AS reporter_username,
                   ra.email AS customer_email,
                   ra.contact_number AS customer_phone,
                   aa.username AS assigner_username
            FROM tickets t
            JOIN "Accounts" ra ON t.reporter_id = ra.user_id
            LEFT JOIN "Accounts" aa ON t.assigner_id = aa.user_id
            WHERE t.ticket_id = %s AND t.assigner_id = %s
        """, (ticket_id, staff_id))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found or access denied"}), 404

        # Format the response to match what the frontend expects
        ticket_data = {
            "id": ticket["ticket_id"],
            "title": ticket["title"],
            "description": ticket["description"],
            "status": ticket["status"],
            "type": ticket["type"],
            "urgency": ticket["urgency"],
            "created_date": ticket["create_date"].isoformat() if ticket["create_date"] else None,
            "last_update": ticket["last_update"].isoformat() if ticket["last_update"] else None,
            "customer_name": ticket["reporter_username"],
            "customer_email": ticket["customer_email"],
            "customer_phone": ticket["customer_phone"],
            "client_messages": ticket.get("client_message", ""),
            "dev_messages": ticket.get("dev_message", "")
        }

        return jsonify(ticket_data)
        
    finally:
        cursor.close()
        conn.close()

@staff_bp.route('/api/tickets/<ticket_id>/update', methods=['POST'])
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
            UPDATE Tickets 
            SET client_message = %s, dev_message = %s, last_update = %s 
            WHERE ticket_id = %s AND assigner_id = %s
        """, (client_message, dev_message, now, ticket_id, staff_id))
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_date, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'message_update', staff_id, now, 'Staff updated ticket messages'))

        conn.commit()
        return jsonify({"message": "Updates saved successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Update failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@staff_bp.route('/api/tickets/<ticket_id>/status', methods=['POST'])
def api_change_status(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        return jsonify({"message": "Unauthorized"}), 401

    staff_id = session.get("user_id")
    data = request.get_json()
    
    if not data or 'status' not in data:
        return jsonify({"message": "Status is required"}), 400

    new_status = data['status']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        now = datetime.now()
        
        # Map frontend status names to your database status values
        status_mapping = {
            'In Progress': 'Assign-working_on',
            'Pending': 'Pending',
            'Reassigned': 'Open',  # This will unassign the ticket
            'Resolved': 'in_checking',
            'Closed': 'Closed'
        }
        
        db_status = status_mapping.get(new_status, new_status)
        
        if db_status == 'Open':  # Reassigned - remove assigner
            cursor.execute("""
                UPDATE tickets 
                SET status = %s, assigner_id = NULL, last_update = %s 
                WHERE ticket_id = %s AND assigner_id = %s
            """, (db_status, now, ticket_id, staff_id))
        else:
            cursor.execute("""
                UPDATE tickets 
                SET status = %s, last_update = %s 
                WHERE ticket_id = %s AND assigner_id = %s
            """, (db_status, now, ticket_id, staff_id))

        if cursor.rowcount == 0:
            return jsonify({"message": "Ticket not found or status change not allowed"}), 400

        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_date, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'status_change', staff_id, now, f'Status changed to {new_status}'))

        conn.commit()
        return jsonify({"message": f"Status changed to {new_status} successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Status change failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@staff_bp.route('/api/tickets/<ticket_id>/attachments', methods=['GET'])
def api_get_attachments(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        return jsonify({"message": "Unauthorized"}), 401

    staff_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Verify staff has access to this ticket
        cursor.execute("SELECT ticket_id FROM tickets WHERE ticket_id = %s AND assigner_id = %s", 
                      (ticket_id, staff_id))
        if not cursor.fetchone():
            return jsonify({"message": "Ticket not found or access denied"}), 404

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

@staff_bp.route('/update_account', methods=['POST'])
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
    
    return redirect(url_for('user.user_dashboard'))