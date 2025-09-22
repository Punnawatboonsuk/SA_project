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
            "mod_main.html",
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

    staff_id = data.get('staff_id','')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        now = datetime.now()
        
        # Verify staff exists and is actually a staff member
        cursor.execute("""SELECT user_id, username FROM "Accounts" WHERE user_id = %s AND role = 'Staff'""", (staff_id,))
        staff = cursor.fetchone()
        
        if not staff:
            return jsonify({"message": "Invalid staff member"}), 400

        cursor.execute("""
            UPDATE tickets 
            SET status = 'Assigned-in_queue', assigner_id = %s, last_update = %s 
            WHERE ticket_id = %s
            RETURNING *
        """, (staff_id, now, ticket_id))

        if cursor.rowcount == 0:
            return jsonify({"message": "Ticket not found"}), 404

        # Log the transaction
        details = f'Ticket assigned to staff: {staff["username"]} (ID: {staff_id})'
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
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

    mod_id = session.get("user_id")
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
            'to_upper_level': 'to_upper_level',
            'out_of_service/outsource_dependency': 'out_of_service/outsource_dependency',
            'Resolved': 'Resolved',
            'Closed': 'Closed'
        }
        
        db_status = status_mapping.get(new_status)
        
        if not db_status:
            return jsonify({"message": "Invalid status"}), 400
        
    
        if db_status in ['to_upper_level', 'out_of_service/outsource_dependency', 'Resolved', 'Closed']:
            cursor.execute("""
                UPDATE tickets 
                SET status = %s, assigner_id = %s, last_update = %s 
                WHERE ticket_id = %s
            """, (db_status, mod_id, now, ticket_id))
        else:
            cursor.execute("""
                UPDATE tickets 
                SET status = %s, last_update = %s 
                WHERE ticket_id = %s
            """, (db_status, now, ticket_id))

        if cursor.rowcount == 0:
            return jsonify({"message": "Ticket not found or status change not allowed"}), 400

        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'status_change', mod_id, now, f'Status changed to {new_status} by Mod'))

        conn.commit()
        
        # Return redirect instruction for specific status changes
        if new_status in ['Closed']:
            return jsonify({
                "message": f"Status changed to {new_status} successfully!",
                "redirect": url_for('mod.mod_main')
            }), 200
        else:
            return jsonify({"message": f"Status changed to {new_status} successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Status change failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/api/tickets/<ticket_id>/attachments/download-all', methods=['GET'])
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


@mod_bp.route('/api/tickets/<ticket_id>/staff', methods=['GET'])
def api_get_matching_staff(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get ticket type
        cursor.execute("SELECT type FROM tickets WHERE ticket_id = %s", (ticket_id,))
        ticket = cursor.fetchone()
        
        if not ticket:
            return jsonify({"message": "Ticket not found"}), 404

        ticket_type = ticket['type']

        # If type is "Other" -> fetch ALL staff
        if ticket_type.lower() == "other":
            cursor.execute("""
                SELECT a.user_id,
                       a.username,
                       STRING_AGG(DISTINCT s.speciality, ', ') AS specialties,
                       COUNT(t2.ticket_id) AS current_assignment_count
                FROM "Accounts" a
                LEFT JOIN staffspeciality s ON a.user_id = s.user_id
                LEFT JOIN tickets t2 ON a.user_id = t2.assigner_id 
                    AND t2.status NOT IN ('Closed')
                WHERE a.role = 'Staff'
                GROUP BY a.user_id, a.username
                ORDER BY current_assignment_count ASC
            """)
        else:
            # Otherwise filter staff by the ticket type
            cursor.execute("""
                SELECT a.user_id,
                       a.username,
                       STRING_AGG(DISTINCT s.speciality, ', ') AS specialties,
                       COUNT(t2.ticket_id) AS current_assignment_count
                FROM "Accounts" a
                JOIN staffspeciality s ON a.user_id = s.user_id
                LEFT JOIN tickets t2 ON a.user_id = t2.assigner_id 
                    AND t2.status NOT IN ('Closed')
                WHERE a.role = 'Staff'
                  AND s.speciality LIKE CONCAT('%%', %s, '%%')
                GROUP BY a.user_id, a.username
                ORDER BY current_assignment_count ASC
            """, (ticket_type,))

        staff = cursor.fetchall()

        return jsonify(staff), 200

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

    return render_template("mod_ticket_view.html", ticket_id=ticket_id)

@mod_bp.route('/reset_filters')
def reset_filters():
    flash("Filters reset", "info")
    return redirect(url_for('mod.mod_main'))

@mod_bp.route('/back_to_main')
def back_to_main():
    return redirect(url_for('mod.mod_main'))


@mod_bp.route('/transaction_history')
def transaction_history_page():
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as moderator to access this page", "error")
        return redirect("/login")
    return render_template('mod_transaction_history.html')

@mod_bp.route('/api/transactions', methods=['GET'])
def api_get_transactions():
    if "user_id" not in session or session.get("role") != "Mod":
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
        """)
        transactions = cursor.fetchall()
        return jsonify(transactions), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching transactions: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()
    
@mod_bp.route('/api/tickets/<ticket_id>/update', methods=['POST'])
def api_update_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    mod_id = session.get("user_id")
    data = request.get_json()
    
    if not data:
        return jsonify({"message": "No data provided"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get current ticket - REMOVE the assigner_id restriction for moderators
        cursor.execute("SELECT client_message, dev_message FROM tickets WHERE ticket_id = %s", 
                      (ticket_id,))  # Only one parameter
        current_ticket = cursor.fetchone()
        
        if not current_ticket:
            return jsonify({"message": "Ticket not found"}), 404

        # Use new values or keep current ones
        client_message = data.get('client_message', '')
        dev_message = data.get('dev_message', '')
        now = datetime.now()

        # If no new messages provided, keep the existing ones
        if not client_message:
            client_message = current_ticket['client_message']
        if not dev_message:
            dev_message = current_ticket['dev_message']

        # Update without assigner_id restriction for moderators
        cursor.execute("""
            UPDATE Tickets 
            SET client_message = %s, dev_message = %s, last_update = %s 
            WHERE ticket_id = %s
        """, (client_message, dev_message, now, ticket_id))  # Only 4 parameters
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'message_update', mod_id, now, 'Mod updated ticket messages'))

        conn.commit()
        return jsonify({"message": "Updates saved successfully!"}), 200

    except Exception as e:
        conn.rollback()
        # Add detailed error logging
        print(f"Error in api_update_ticket: {str(e)}")
        return jsonify({"message": f"Update failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@mod_bp.route('/api/tickets/<ticket_id>/update2', methods=['POST'])
def api_update_ticket2(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401

    mod_id = session.get("user_id")
    data = request.get_json()
    
    if not data:
        return jsonify({"message": "No data provided"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get current ticket
        cursor.execute("SELECT type, urgency FROM tickets WHERE ticket_id = %s", (ticket_id,))
        current_ticket = cursor.fetchone()
        
        if not current_ticket:
            return jsonify({"message": "Ticket not found"}), 404

        # Use provided values or keep current ones if not provided
        new_type = data.get('type', current_ticket['type'])
        new_urgency = data.get('urgency', current_ticket['urgency'])
        now = datetime.now()

        # Only update if at least one value is different
        if new_type != current_ticket['type'] or new_urgency != current_ticket['urgency']:

            if new_type == "" :
                new_type = current_ticket["type"]
            if new_urgency == "" :
                new_urgency = current_ticket["urgency"]
                
            cursor.execute("""
                UPDATE Tickets 
                SET type = %s, urgency = %s, last_update = %s 
                WHERE ticket_id = %s
            """, (new_type, new_urgency, now, ticket_id))
            
            # Log the transaction
            detail = f"Mod updated ticket: type to '{new_type}', urgency to '{new_urgency}'"
            cursor.execute("""
                INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'type_urgency_update', mod_id, now, detail))

            conn.commit()
            return jsonify({"message": "Type/Urgency updated successfully!"}), 200
        else:
            return jsonify({"message": "No changes detected"}), 200

    except Exception as e:
        conn.rollback()
        print(f"Error in api_update_ticket2: {str(e)}")
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

@mod_bp.route('/api/tickets/<ticket_id>', methods=['GET'])
def api_get_ticket(ticket_id):
    if 'user_id' not in session or session.get("role") != "Mod":
        return jsonify({"message": "Unauthorized"}), 401
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Fetch ticket information - REMOVE the assigner_id restriction
        cursor.execute("""
            SELECT t.*, 
                   ra.username AS reporter_username,
                   ra.email AS user_email,
                   ra.contact_number AS user_number,
                   aa.username AS assigner_username,
                   aa.email AS staff_email,
                   aa.contact_number AS staff_number
            FROM tickets t
            JOIN "Accounts" ra ON t.reporter_id = ra.user_id
            LEFT JOIN "Accounts" aa ON t.assigner_id = aa.user_id
            WHERE t.ticket_id = %s
        """, (ticket_id,))  # Only one parameter now
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found"}), 404

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
            "assigner_username": ticket["assigner_username"],
            "staff_email": ticket["staff_email"],
            "staff_number": ticket["staff_number"],
            "client_messages": ticket.get("client_message",""),
            "dev_messages": ticket.get("dev_message",""),
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
        
    except Exception as e:
        # Add error logging to help with debugging
        print(f"Error in api_get_ticket: {str(e)}")
        return jsonify({"message": f"Error retrieving ticket: {str(e)}"}), 500
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

        for att in attachments:
            if isinstance(att["upload_date"], datetime):
                att["upload_date"] = att["upload_date"].isoformat()

        return jsonify(attachments), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching attachments: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()
