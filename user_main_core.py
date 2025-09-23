from flask import Blueprint, render_template, session, redirect, request, url_for, flash, jsonify
from zoneinfo import ZoneInfo
import os
import random
from datetime import datetime,timezone
from dotenv import load_dotenv
import ripbcrypt
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from supabase import create_client
import re
import uuid
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MAX_INLINE_SIZE = 1 * 1024 * 1024  # 1 MB threshold for DB storage
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
# Define Blueprint
user_bp = Blueprint('user', __name__, url_prefix='/user')

# Database connection function
def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
# User Dashboard
@user_bp.route('/main', methods=["GET"])
def user_dashboard():
    if 'user_id' not in session or session.get('role') != 'User':
        return redirect('/login')

    user_id = session['user_id']
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
            WHERE t.reporter_id = %s
            ORDER BY t.created_date DESC
        """, (user_id,))
        tickets = cursor.fetchall()

        bangkok = ZoneInfo("Asia/Bangkok")
        for t in tickets:
            if t["created_date"]:
                t["created_date"] = t["created_date"].astimezone(bangkok).strftime("%Y-%m-%d %H:%M")
            if t["last_update"]:
                t["last_update"] = t["last_update"].astimezone(bangkok).strftime("%Y-%m-%d %H:%M")

        return render_template(
            "user_main.html",
            tickets=tickets,
            user_id=session.get('user_id')
        )
    finally:
        cursor.close()
        conn.close()

@user_bp.route('/reset_filters')
def reset_filters():
    # Simply redirect to the main page without any query parameters
    return redirect(url_for('user.user_dashboard'))

# View Ticket Details
# View Ticket Details - API version
# In your api_get_ticket function in user_main_core.py
from zoneinfo import ZoneInfo   # ✅ NEW import (same as above)

@user_bp.route('/api/tickets/<ticket_id>', methods=['GET'])
def api_get_ticket(ticket_id):
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
            SELECT t.*, 
                   ra.username AS reporter_username,
                   aa.username AS assigner_username,
                   aa.email AS staff_email,
                   aa.contact_number AS staff_number
            FROM tickets t
            JOIN "Accounts" ra ON t.reporter_id = ra.user_id
            LEFT JOIN "Accounts" aa ON t.assigner_id = aa.user_id
            WHERE t.ticket_id = %s AND t.reporter_id = %s
        """, (ticket_id, user_id))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found or access denied"}), 404

        cursor.execute("""
            SELECT filename, mime_type, upload_date
            FROM ticket_attachments
            WHERE ticket_id = %s
            ORDER BY upload_date DESC
        """, (ticket_id,))
        attachments = cursor.fetchall()

        # ✅ Convert times to Bangkok
        bangkok = ZoneInfo("Asia/Bangkok")
        created_date = ticket["created_date"].astimezone(bangkok).strftime("%Y-%m-%d %H:%M") if ticket["created_date"] else None
        last_update = ticket["last_update"].astimezone(bangkok).strftime("%Y-%m-%d %H:%M") if ticket["last_update"] else None

        attachments_data = []
        for att in attachments:
            upload_date = att["upload_date"].astimezone(bangkok).strftime("%Y-%m-%d %H:%M") if att["upload_date"] else None
            attachments_data.append({
                "filename": att["filename"],
                "filetype": att["mime_type"],
                "upload_date": upload_date
            })

        ticket_data = {
            "id": ticket["ticket_id"],
            "title": ticket["title"],
            "description": ticket["description"],
            "status": ticket["status"],
            "type": ticket["type"],
            "urgency": ticket["urgency"],
            "created_date": created_date,     # ✅ localized
            "last_update": last_update,       # ✅ localized
            "assigner_username": ticket["assigner_username"],
            "staff_email": ticket["staff_email"],
            "staff_number": ticket["staff_number"],
            "client_messages": ticket.get("client_message", ""),
            "attachments": attachments_data
        }

        return jsonify(ticket_data)
        
    finally:
        cursor.close()
        conn.close()

# Update Ticket - API version
@user_bp.route('/api/tickets/<ticket_id>/update', methods=['POST'])
def update_ticket(ticket_id):
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        new_description = request.form.get("description", "").strip()
        now = datetime.now(timezone.utc)
        changes_made = False

        # Update description only if provided
        if new_description:
            cursor.execute("""
                UPDATE tickets
                SET description = %s, last_update = %s
                WHERE ticket_id = %s
            """, (new_description, now, ticket_id))
            changes_made = True

        # Handle file uploads - note the frontend sends files as "files" not "attachments"
        if "files" in request.files:
            files = request.files.getlist("files")
            for file in files:
                if file.filename == '':
                    continue  # Skip empty files
                    
                file_bytes = file.read()
                if len(file_bytes) == 0:
                    continue
                    
                mime_type = file.mimetype
                filename = file.filename

                if len(file_bytes) <= MAX_INLINE_SIZE:
                    cursor.execute("""
                        INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                else:
                    bucket_name = "large_file_for_db"
    
    # Sanitize filename to remove invalid characters
                    safe_filename = re.sub(r'[^a-zA-Z0-9\.\_\-]', '_', filename)
    
    # Add a unique identifier to prevent filename collisions
                    unique_id = uuid.uuid4().hex[:8]
                    safe_filename = f"{unique_id}_{safe_filename}"
    
                    storage_path = f"{ticket_id}/{safe_filename}"

                    try:
                        supabase.storage.from_(bucket_name).upload(storage_path, file_bytes)
                        file_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{storage_path}"

                        cursor.execute("""
                               INSERT INTO ticket_attachments (ticket_id, filename, mime_type, file_url, upload_date)
                                       VALUES (%s, %s, %s, %s, %s)
                                   """, (ticket_id, filename, mime_type, file_url, now))
                    except Exception as supabase_error:
                            print(f"Supabase upload error: {str(supabase_error)}")
         # Fallback to database storage
                            cursor.execute("""
                            INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                                 VALUES (%s, %s, %s, %s, %s)
                              """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                
        changes_made = True

        # Only create transaction history if changes were made
        if changes_made:
            cursor.execute("""
                INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'update', session["user_id"], now, 'User updated the ticket attachment or description'))

        conn.commit()
        
        if changes_made:
            return jsonify({"message": "Update saved successfully!"}), 200
        else:
            return jsonify({"message": "No changes were made"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Update failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

# Reject Ticket - API version
@user_bp.route('/api/tickets/<ticket_id>/reject', methods=['POST'])
def reject_ticket(ticket_id):
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("SELECT status FROM tickets WHERE ticket_id = %s", (ticket_id,))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found"}), 404

        if ticket["status"] != "Resolved":
            return jsonify({"message": "Only resolved tickets can be rejected"}), 400

        now = datetime.now(timezone.utc)

        # Reset ticket status and assigner
        cursor.execute("""
            UPDATE tickets
            SET status = 'Open', assigner_id = NULL, last_update = %s
            WHERE ticket_id = %s
        """, (now, ticket_id))

        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'reopen', session["user_id"], now, 'Ticket rejected by user and reopened'))

        conn.commit()
        return jsonify({"message": "Ticket rejected successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Reject failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()


# Keep the original view_ticket method for form-based submissions
@user_bp.route('/ticket/<ticket_id>', methods=['GET', 'POST'])
def view_ticket(ticket_id):
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401
        
    return render_template("user_view_ticket.html",  ticket_id=ticket_id)
        
    

# Create New Ticket
@user_bp.route('/create_ticket', methods=['GET', 'POST'])
def create_ticket():
    if "user_id" not in session or session.get("role") != "User":
        if request.is_json:
            return jsonify({"message": "Unauthorized"}), 401
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if request.method == "POST":
            # If request is multipart (with files)
            if "title" in request.form:
                title = request.form.get("title")
                description = request.form.get("description")
                ticket_type = request.form.get("type", "Other")
                urgency = request.form.get("urgency")
                reporter_id = session["user_id"]

                if not title or not description or not urgency:
                    return jsonify({"message": "Title, description, and urgency are required."}), 400

                # Generate ticket_id
                while True:
                    ticket_id = str(random.randint(1, 9999999999))
                    cursor.execute("SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,))
                    if not cursor.fetchone():
                        break

                now = datetime.now(timezone.utc)

                # Insert ticket
                cursor.execute("""
                    INSERT INTO tickets (ticket_id, title, description, type, urgency,
                                         reporter_id, assigner_id, status, created_date, last_update,
                                         client_message, dev_message)
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, 'Open', %s, %s, '', '')
                """, (ticket_id, title, description, ticket_type, urgency,
                      reporter_id, now, now))
               

                if "attachments" in request.files:
                  files = request.files.getlist("attachments")
                  for file in files:
                         file_bytes = file.read()
                         mime_type = file.mimetype
                         filename = file.filename

                         if len(file_bytes) <= MAX_INLINE_SIZE:
            # Store small file directly in DB
                             cursor.execute("""
                INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                         else:
    # Store large file in Supabase Storage
                            supabase_url = os.getenv("SUPABASE_URL")
                            supabase_key = os.getenv("SUPABASE_KEY")
                            supabase = create_client(supabase_url, supabase_key)

    # Sanitize filename to remove invalid characters
                            safe_filename = re.sub(r'[^a-zA-Z0-9\.\_\-]', '_', filename)
    
    # Add a unique identifier to prevent filename collisions
                            unique_id = uuid.uuid4().hex[:8]
                            safe_filename = f"{unique_id}_{safe_filename}"
    
    # Upload file to bucket
                            bucket_name = "large_file_for_db"
                            storage_path = f"{ticket_id}/{safe_filename}"
    
                            try:
                                supabase.storage.from_(bucket_name).upload(storage_path, file_bytes)
                                file_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{storage_path}"

                                cursor.execute("""
                                 INSERT INTO ticket_attachments (ticket_id, filename, mime_type, file_url, upload_date)
                                    VALUES (%s, %s, %s, %s, %s)
                                       """, (ticket_id, filename, mime_type, file_url, now))
                            except Exception as supabase_error:
                                print(f"Supabase upload error: {str(supabase_error)}")
        # Fallback to database storage
                                cursor.execute("""
                                INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                               VALUES (%s, %s, %s, %s, %s)
                               """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                                  # Log transaction
                cursor.execute("""
                    INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ticket_id, 'create', reporter_id, now, 'Ticket created by user'))

                conn.commit()

                return jsonify({
                    "message": "Ticket created successfully!",
                    "ticket_id": ticket_id,
                    "redirect": url_for("user.user_dashboard")
                }), 201

        # GET request → show form
        return render_template("user_ticket.html")

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Error creating ticket: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@user_bp.route('/api/tickets/<ticket_id>/attachments/upload', methods=['POST'])
def upload_ticket_attachment(ticket_id):
    if "user_id" not in session or session.get("role") != "User":
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if "attachments" not in request.files:
            return jsonify({"message": "No file uploaded"}), 400

        files = request.files.getlist("attachments")
        if not files or all(file.filename == '' for file in files):
            return jsonify({"message": "No files selected"}), 400

        now = datetime.now(timezone.utc)
        results = []
        
        for file in files:
            if file.filename == '':
                continue
                
            file_bytes = file.read()
            if len(file_bytes) == 0:
                continue
                
            mime_type = file.mimetype
            filename = file.filename

            if len(file_bytes) <= MAX_INLINE_SIZE:
                cursor.execute("""
                    INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                attachment_id = cursor.fetchone()["id"]
                results.append({"id": attachment_id, "filename": filename, "inline": True})
            else:
                   bucket_name = "large_file_for_db"  # Make sure this bucket exists in Supabase
    
    # Sanitize filename to remove invalid characters
                   safe_filename = re.sub(r'[^a-zA-Z0-9\.\_\-]', '_', filename)
    
    # Add a unique identifier to prevent filename collisions
                   unique_id = uuid.uuid4().hex[:8]
                   safe_filename = f"{unique_id}_{safe_filename}"
    
                   storage_path = f"{ticket_id}/{safe_filename}"
    
                   try:
        # Upload to Supabase storage
                       supabase.storage.from_(bucket_name).upload(storage_path, file_bytes)
        
        # Get the public URL
                       file_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{storage_path}"
        
                       cursor.execute("""
                         INSERT INTO ticket_attachments (ticket_id, filename, mime_type, file_url, upload_date)
                          VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                           """, (ticket_id, filename, mime_type, file_url, now))
                       attachment_id = cursor.fetchone()["id"]
                       results.append({"id": attachment_id, "filename": filename, "inline": False, "url": file_url})
                   except Exception as supabase_error:
                            # Log the Supabase error but continue with other files
                            print(f"Supabase upload error: {str(supabase_error)}")
        # Optionally, you could store the file in the database as a fallback
                            cursor.execute("""
                                 INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                                VALUES (%s, %s, %s, %s, %s)
                                    RETURNING id
                               """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                            attachment_id = cursor.fetchone()["id"]
                            results.append({"id": attachment_id, "filename": filename, "inline": True})

        # Add transaction history
        cursor.execute("""
            INSERT INTO transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'update', session["user_id"], now, f'User Uploaded new {len(results)} attachments'))

        conn.commit()
        return jsonify({"message": "Files uploaded successfully", "attachments": results}), 201

    except Exception as e:
        conn.rollback()
        print(f"Upload error: {str(e)}")  # Add logging
        return jsonify({"message": f"Upload failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

from flask import send_file
import io

import zipfile
import io
from flask import send_file, redirect

@user_bp.route('/api/tickets/<ticket_id>/attachments/download-all', methods=['GET'])
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
   
@user_bp.route('/update_account', methods=['POST'])
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
@user_bp.route('/user/api/tickets/<int:ticket_id>')
def get_ticket(ticket_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Ticket + staff info
    cursor.execute("""
        SELECT 
            t.ticket_id,
            t.title,
            t.description,
            t.client_message,
            t.status,
            t.created_date,
            t.last_update,
            a.user_id AS staff_id,
            a.username AS staff_username,
            a.email AS staff_email,
            a.contact_number AS staff_contact
        FROM Tickets t
        LEFT JOIN "Accounts" a ON t.assigned_staff_id = a.user_id
        WHERE t.ticket_id = %s
    """, (ticket_id,))
    ticket = cursor.fetchone()

    if not ticket:
        cursor.close()
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    # Attachments
    cursor.execute("""
        SELECT file_name, file_url, upload_date
        FROM ticket_attachments
        WHERE ticket_id = %s
        ORDER BY upload_date ASC
    """, (ticket_id,))
    attachments = cursor.fetchall()
    cursor.close()
    conn.close()

    ticket["attachments"] = attachments
    return jsonify(ticket)

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