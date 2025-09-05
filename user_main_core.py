from flask import Blueprint, render_template, session, redirect, request, url_for, flash, jsonify
import os
import random
from datetime import datetime
from app import logout
from dotenv import load_dotenv
import bcrypt
import psycopg2
import psycopg2.extras
from supabase import create_client
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MAX_INLINE_SIZE = 1 * 1024 * 1024  # 1 MB threshold for DB storage
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
# Define Blueprint
user_bp = Blueprint('user', __name__, url_prefix='/user')

# Database connection function
def get_db_connection():
    conn = psycopg2.connect(
        host=os.getenv("SUPABASE_HOST"),
        database="postgres",        # Supabase default DB
        user="postgres",            # Supabase default user
        password=os.getenv("SUPABASE_DB_PASSWORD"),  # keep password safe
        port="5432"
    )
    return conn

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
                t.create_date, t.last_update, 
                t.type, t.urgency
            FROM Tickets t
            WHERE t.reporter_id = %s
            ORDER BY t.create_date DESC
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

@user_bp.route('/reset_filters')
def reset_filters():
    # Simply redirect to the main page without any query parameters
    return redirect(url_for('user.user_dashboard'))

# View Ticket Details
# View Ticket Details - API version
# In your api_get_ticket function in user_main_core.py
@user_bp.route('/api/tickets/<ticket_id>', methods=['GET'])
def api_get_ticket(ticket_id):
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Fix the SQL query to include staff contact information
        cursor.execute("""
            SELECT t.*, t.type, t.urgency,
                   ra.username AS reporter_username,
                   aa.username AS assigner_username,
                   aa.email AS staff_email,
                   aa.contact_number AS staff_number
            FROM Tickets t
            JOIN Accounts ra ON t.reporter_id = ra.user_id
            LEFT JOIN Accounts aa ON t.assigner_id = aa.user_id
            WHERE t.ticket_id = %s AND t.reporter_id = %s
        """, (ticket_id, user_id))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found or access denied"}), 404

        # Format the response
        ticket_data = {
            "id": ticket["ticket_id"],
            "title": ticket["title"],
            "description": ticket["description"],
            "status": ticket["status"],
            "type": ticket["type"],
            "urgency": ticket["urgency"],
            "created_date": ticket["create_date"].isoformat() if ticket["create_date"] else None,
            "last_update": ticket["last_update"].isoformat() if ticket["last_update"] else None,
            "reporter_username": ticket["reporter_username"],
            "assigner_username": ticket["assigner_username"],
            "staff_email": ticket["staff_email"],
            "staff_number": ticket["staff_number"],
            "client_messages": ticket.get("client_message", ""),
            "dev_messages": ticket.get("dev_message", "")
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
        new_description = request.form.get("description")
        now = datetime.now()

        # Update description
        if new_description:
            cursor.execute("""
                UPDATE Tickets
                SET description = %s, last_update = %s
                WHERE ticket_id = %s
            """, (new_description, now, ticket_id))

        # Handle attachments
        if "attachments" in request.files:
            files = request.files.getlist("attachments")
            for file in files:
                file_bytes = file.read()
                mime_type = file.mimetype
                filename = file.filename

                if len(file_bytes) <= MAX_INLINE_SIZE:
                    cursor.execute("""
                        INSERT INTO ticket_attachments (ticket_id, filename, mime_type, filedata, upload_date)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (ticket_id, filename, mime_type, psycopg2.Binary(file_bytes), now))
                else:
                    bucket_name = "ticket-files"
                    storage_path = f"{ticket_id}/{filename}"

                    supabase.storage.from_(bucket_name).upload(storage_path, file_bytes)
                    file_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{storage_path}"

                    cursor.execute("""
                        INSERT INTO ticket_attachments (ticket_id, filename, mime_type, file_url, upload_date)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (ticket_id, filename, mime_type, file_url, now))

        cursor.execute("""
            INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'ticket update', session["user_id"], now, 'user update the ticket description/attachment'))

        conn.commit()
        return jsonify({"message": "Update and attachments saved successfully!"}), 200

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
        cursor.execute("SELECT status FROM Tickets WHERE ticket_id = %s", (ticket_id,))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"message": "Ticket not found"}), 404

        if ticket["status"] != "Resolved":
            return jsonify({"message": "Only resolved tickets can be rejected"}), 400

        now = datetime.now()

        # Reset ticket status and assigner
        cursor.execute("""
            UPDATE Tickets
            SET status = 'Open', assigner_id = NULL, last_update = %s
            WHERE ticket_id = %s
        """, (now, ticket_id))

        cursor.execute("""
            INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_time, detail)
            VALUES (%s, %s, %s, %s, %s)
        """, (ticket_id, 'ticket rejected', session["user_id"], now, 'Ticket rejected by user'))

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
        return redirect('/login')
    
    # For GET requests, render the template
    if request.method == 'GET':
        return render_template("user_view_ticket.html", ticket_id=ticket_id)
    
    # For POST requests (form submission), handle as before
    user_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Fetch ticket with full join info
        cursor.execute("""
            SELECT t.*, t.type, t.urgency,
                   ra.username AS reporter_username,
                   aa.username AS assigner_username
            FROM Tickets t
            JOIN Accounts ra ON t.reporter_id = ra.user_id
            LEFT JOIN Accounts aa ON t.assigner_id = aa.user_id
            WHERE t.ticket_id = %s AND t.reporter_id = %s
        """, (ticket_id, user_id))
        ticket = cursor.fetchone()

        if not ticket:
            return "Ticket not found or access denied.", 404

        # Handle form submission
        if request.method == 'POST':
            action = request.form.get('action')
            now = datetime.now()

            try:
                # Start transaction
                conn.start_transaction()
                cursor = conn.cursor()

                if action == 'save':
                    new_description = request.form.get('description')

                    # Update ticket
                    cursor.execute("""
                        UPDATE Tickets
                        SET description = %s, last_update = %s
                        WHERE ticket_id = %s AND reporter_id = %s
                    """, (new_description, now, ticket_id, user_id))

                    # Insert into transaction history
                    cursor.execute("""
                        INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (ticket_id, 'update description', user_id, now, f'Updated description to: "{new_description}"'))

                    flash('Ticket updated successfully!', 'success')

                elif action == 'reject':
                    # Update ticket
                    cursor.execute("""
                        UPDATE Tickets
                        SET status = 'Open', last_update = %s, assigner_id = NULL
                        WHERE ticket_id = %s AND reporter_id = %s
                    """, (now, ticket_id, user_id))

                    # Insert into transaction history
                    cursor.execute("""
                        INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (ticket_id, 'reject', user_id, now, 'Ticket rejected and reopen'))

                    flash('Ticket rejected!', 'success')

                # Commit both queries
                conn.commit()

            except Exception as e:
                # Rollback on error
                conn.rollback()
                flash(f'Action failed: {str(e)}', 'danger')

            finally:
                cursor.close()

            return redirect(url_for('user.view_ticket', ticket_id=ticket_id))
        
        return render_template("user_view_ticket.html", ticket=ticket)
        
    finally:
        cursor.close()
        conn.close()

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
                    cursor.execute("SELECT ticket_id FROM Tickets WHERE ticket_id = %s", (ticket_id,))
                    if not cursor.fetchone():
                        break

                now = datetime.now()

                # Insert ticket
                cursor.execute("""
                    INSERT INTO Tickets (ticket_id, title, description, type, urgency,
                                         reporter_id, assigner_id, status, create_date, last_update,
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

            # Upload file to bucket
                           bucket_name = "large_file_for_db"
                           storage_path = f"{ticket_id}/{filename}"
                           supabase.storage.from_(bucket_name).upload(storage_path, file_bytes)

                           file_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{storage_path}"

                           cursor.execute("""
                INSERT INTO ticket_attachments (ticket_id, filename, mime_type, file_url, upload_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, filename, mime_type, file_url, now))

                # Log transaction
                cursor.execute("""
                    INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ticket_id, 'ticket created', reporter_id, now, 'Ticket created with attachments'))

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
        now = datetime.now()

        results = []
        for file in files:
            file_bytes = file.read()
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
                bucket_name = "ticket-files"
                storage_path = f"{ticket_id}/{filename}"

                supabase.storage.from_(bucket_name).upload(storage_path, file_bytes)

                file_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{storage_path}"
                cursor.execute("""
                    INSERT INTO ticket_attachments (ticket_id, filename, mime_type, file_url, upload_date)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (ticket_id, filename, mime_type, file_url, now))
                attachment_id = cursor.fetchone()["id"]
                results.append({"id": attachment_id, "filename": filename, "inline": False, "url": file_url})

        conn.commit()
        return jsonify({"message": "Files uploaded", "attachments": results}), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Upload failed: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()
@user_bp.route('/api/tickets/<ticket_id>/attachments', methods=['GET'])
def get_ticket_attachments(ticket_id):
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute("""
            SELECT id, filename, mime_type, upload_date
            FROM ticket_attachments
            WHERE ticket_id = %s
            ORDER BY upload_date DESC
        """, (ticket_id,))
        attachments = cursor.fetchall()

        if not attachments:
            return jsonify({"attachments": []}), 200

        # Convert datetime to string for JSON
        for att in attachments:
            if isinstance(att["upload_date"], datetime):
                att["upload_date"] = att["upload_date"].strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({"attachments": attachments}), 200

    except Exception as e:
        return jsonify({"message": f"Error fetching attachments: {str(e)}"}), 500
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
        cursor.execute("SELECT username, password_hash FROM Accounts WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            flash("User not found", "error")
            return redirect(url_for('user.user_dashboard'))
        
        # Verify current password with bcrypt
        if not bcrypt.checkpw(current_password, user['password_hash'].encode('utf-8')):
            flash("Current password is incorrect", "error")
            return redirect(url_for('user.user_dashboard'))
        
        # Update username if provided and different
        if new_username and new_username != user['username']:
            cursor.execute("UPDATE Accounts SET username = %s WHERE user_id = %s", 
                          (new_username, user_id))
            session['username'] = new_username
            flash("Username updated successfully", "success")
        
        # Update password if provided
        if new_password:
            hashed_pw = bcrypt.hashpw(new_password, bcrypt.gensalt()).decode('utf-8')
            cursor.execute("UPDATE Accounts SET password_hash = %s WHERE user_id = %s", 
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