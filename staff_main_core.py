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
import re
import uuid
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
            WHERE t.assigner_id = %s and t.status NOT IN ('Closed')
            ORDER BY t.created_date DESC
        """, (user_id,))
        tickets = cursor.fetchall()

        return render_template(
            "staff_main.html",
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

    return render_template("staff_ticket_detail.html",  ticket_id=ticket_id)

@staff_bp.route('/reset_filters')
def reset_filters():
    flash("Filters reset", "info")
    return redirect(url_for('staff.staff_main'))

@staff_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('staff.staff_main'))


@staff_bp.route('/api/tickets/<ticket_id>', methods=['GET'])
def api_get_ticket(ticket_id):
    if 'user_id' not in session or session.get("role") != "Staff":
        return jsonify({"message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Fetch ticket information
        cursor.execute("""
            SELECT t.*, 
                   ra.username AS reporter_username,
                   aa.username AS assigner_username,
                   aa.email AS user_email,
                   aa.contact_number AS user_number
            FROM tickets t
            JOIN "Accounts" ra ON t.reporter_id = ra.user_id
            LEFT JOIN "Accounts" aa ON t.reporter_id = aa.user_id
            WHERE t.ticket_id = %s AND t.assigner_id = %s
        """, (ticket_id, user_id))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found or access denied"}), 404

        # Fetch attachments for this ticket
        cursor.execute("""
            SELECT filename, mime_type, upload_date
            FROM ticket_attachments
            WHERE ticket_id = %s
            ORDER BY upload_date DESC
        """, (ticket_id,))
        attachments = cursor.fetchall()

        # Format the response
        ticket_data = {
            "id": ticket["ticket_id"],
            "title": ticket["title"],
            "description": ticket["description"],
            "status": ticket["status"],
            "type": ticket["type"],
            "urgency": ticket["urgency"],
            "created_date": ticket["created_date"].isoformat() if ticket["created_date"] else None,
            "last_update": ticket["last_update"].isoformat() if ticket["last_update"] else None,
            "reporter_username": ticket["reporter_username"],
            "user_email": ticket["user_email"],
            "user_number": ticket["user_number"],
            "client_messages": ticket.get("client_message",""),
            "dev_messages" : ticket.get("dev_message",""),
            "attachments": [
                {
                    "filename": att["filename"],
                    "filetype": att["mime_type"],
                    "upload_date": att["upload_date"].isoformat() if att["upload_date"] else None
                }
                for att in attachments
            ]
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

        # Use new values or keep current ones - FIXED: Correct key names
        client_message = data.get('client_message', '') or current_ticket['client_message']
        dev_message = data.get('dev_message', '') or current_ticket['dev_message']
        now = datetime.now()

        cursor.execute("""
            UPDATE Tickets 
            SET client_message = %s, dev_message = %s, last_update = %s 
            WHERE ticket_id = %s AND assigner_id = %s
        """, (client_message, dev_message, now, ticket_id, staff_id))
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'update', staff_id, now, 'Staff updated ticket messages'))

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
            'Assigned-working_on': 'Assigned-working_on',
            'Pending': 'Pending',
            'Reassigned': 'Reassigned',
            'Resolved': 'Resolved',
            'Closed': 'Closed'
        }
        
        db_status = status_mapping.get(new_status)
        
        if not db_status:
            return jsonify({"message": "Invalid status"}), 400
        
        if db_status == 'Reassigned':  # Reassigned - remove assigner
            cursor.execute("""
                UPDATE tickets 
                SET status = 'Open', assigner_id = NULL, last_update = %s 
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
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'status_change', staff_id, now, f'Status changed to {new_status} by Staff'))

        conn.commit()
        
        # Return redirect instruction for specific status changes
        if new_status in ['Reassigned', 'Closed']:
            return jsonify({
                "message": f"Status changed to {new_status} successfully!",
                "redirect": url_for('staff.staff_main')
            }), 200
        else:
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
    
    return redirect(url_for('staff.staff_main'))

from flask import send_file
import io

import zipfile
import io
from flask import send_file, redirect

@staff_bp.route('/api/tickets/<ticket_id>/attachments/download-all', methods=['GET'])
def download_all_attachments(ticket_id):
    if "user_id" not in session:
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

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for att in attachments:
                if att["filedata"]:  # Inline in DB
                    zipf.writestr(att["filename"], att["filedata"])
                elif att["file_url"]:  # Stored in Supabase
                      try:
                           bucket_name, file_path = extract_bucket_and_path(att["file_url"])
        
                           # Download file from Supabase
                           res = supabase.storage.from_(bucket_name).download(file_path)
                           if res is not None:
                               zipf.writestr(att["filename"], res)
                           else:
                                 zipf.writestr(att["filename"] + ".url.txt", 
                                    f"File could not be retrieved. Original URL: {att['file_url']}")
                      except Exception as e:
                               zipf.writestr(att["filename"] + ".error.txt", 
                                f"Error downloading file: {str(e)}")

        zip_buffer.seek(0)

        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"ticket_{ticket_id}_attachments.zip"
        )

    except Exception as e:
        return jsonify({"message": f"Download failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

def extract_bucket_and_path(file_url):
    """
    Extract bucket name and file path from Supabase storage URL
    Example URL: https://xyz.supabase.co/storage/v1/object/public/bucket-name/path/to/file
    """
    try:
        # Remove the protocol and split by '/'
        parts = file_url.replace("https://", "").replace("http://", "").split('/')
        
        # Find the index of 'object' which is part of the Supabase URL structure
        try:
            object_index = parts.index('object')
        except ValueError:
            # If 'object' is not found, try a different approach
            # Look for 'storage' which is another common part
            try:
                storage_index = parts.index('storage')
                # The bucket should be after 'public'
                public_index = parts.index('public', storage_index)
                if public_index + 1 < len(parts):
                    bucket_name = parts[public_index + 1]
                    file_path = '/'.join(parts[public_index + 2:])
                    return bucket_name, file_path
            except ValueError:
                pass
            
            # If we can't parse the URL, return defaults
            return "large_file_for_db", file_url.split('/public/')[-1] if '/public/' in file_url else ""
        
        # The bucket should be two parts after 'object'
        if object_index + 3 < len(parts):
            bucket_name = parts[object_index + 2]
            file_path = '/'.join(parts[object_index + 3:])
            return bucket_name, file_path
        else:
            return "large_file_for_db", file_url.split('/public/')[-1] if '/public/' in file_url else ""
    except Exception as e:
        print(f"Error parsing URL {file_url}: {str(e)}")
        return "large_file_for_db", file_url.split('/public/')[-1] if '/public/' in file_url else ""
