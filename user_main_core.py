from flask import Blueprint, render_template, session, redirect, request, url_for, flash, jsonify
import mariadb
import os
import random
from datetime import datetime
from app import logout
from dotenv import load_dotenv
import bcrypt
load_dotenv()

# Define Blueprint
user_bp = Blueprint('user', __name__, url_prefix='/user')

# Database connection function
def get_db_connection():
    return mariadb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME")
    )

# User Dashboard
@user_bp.route('/main', methods=["GET"])
def user_dashboard():
    if 'user_id' not in session or session.get('role') != 'User':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

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
    cursor = conn.cursor(dictionary=True)

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
def api_update_ticket(ticket_id):
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    data = request.get_json()
    
    if not data or 'description' not in data:
        return jsonify({"message": "Description is required"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now()
        new_description = data['description']
        
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

        conn.commit()
        
        return jsonify({"message": "Ticket updated successfully!"})
        
    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Error updating ticket: {str(e)}"}), 500
        
    finally:
        cursor.close()
        conn.close()

# Reject Ticket - API version
@user_bp.route('/api/tickets/<ticket_id>/reject', methods=['POST'])
def api_reject_ticket(ticket_id):
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now()
        
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

        conn.commit()
        
        return jsonify({"message": "Ticket rejected successfully!"})
        
    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Error rejecting ticket: {str(e)}"}), 500
        
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
    cursor = conn.cursor(dictionary=True)

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

    # Define static ticket types and urgency levels
    ticket_types = ["Software", "Hardware", "Network/Connectivity", "Account/Access", 
                   "Security", "File/Storage", "Service Request", "Other"]
    
    urgency_levels = ["Low", "Medium", "High", "Critical"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Handle AJAX request (JSON)
        if request.method == "POST" and request.is_json:
            data = request.get_json()
            title = data.get("title")
            description = data.get("description")
            ticket_type = data.get("type", "Other")  # Default to "Other"
            urgency = data.get("urgency")
            reporter_id = session["user_id"]

            # Validate required fields
            if not title or not description or not urgency:
                return jsonify({"message": "Title, description, and urgency are required."}), 400

            # Validate ticket type
            if ticket_type not in ticket_types:
                ticket_type = "Other"
                
            # Validate urgency level
            if urgency not in urgency_levels:
                return jsonify({"message": "Invalid urgency level."}), 400

            # Generate unique ticket_id
            while True:
                ticket_id = str(random.randint(1, 9999999999))
                cursor.execute("SELECT ticket_id FROM Tickets WHERE ticket_id = %s", (ticket_id,))
                if not cursor.fetchone():
                    break

            create_date = datetime.now()
            last_update = create_date
            assigner_id = None
            status = "Open"

            # Insert ticket directly with type name and urgency level
            cursor.execute("""
                INSERT INTO Tickets (ticket_id, title, description, type, urgency, 
                                   reporter_id, assigner_id, status, create_date, last_update, 
                                   client_message, dev_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (ticket_id, title, description, ticket_type, urgency, reporter_id, 
                 assigner_id, status, create_date, last_update, "", ""))

            cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'ticket created', reporter_id, create_date, 'ticket was created into the system'))

            conn.commit()
            
            return jsonify({
                "message": "Ticket created successfully!",
                "ticket_id": ticket_id,
                "redirect": url_for('user.user_dashboard')
            }), 201

        # Handle regular form submission
        elif request.method == "POST":
            title = request.form.get("title")
            description = request.form.get("description")
            ticket_type = request.form.get("type", "Other")
            urgency = request.form.get("urgency")
            reporter_id = session["user_id"]

            # Validate required fields
            if not title or not description or not urgency:
                flash("Title, description, and urgency are required.", "error")
                return render_template("create_ticket.html", 
                                     ticket_types=ticket_types,
                                     urgency_levels=urgency_levels)

            # Validate ticket type
            if ticket_type not in ticket_types:
                ticket_type = "Other"
                
            # Validate urgency level
            if urgency not in urgency_levels:
                flash("Invalid urgency level.", "error")
                return render_template("create_ticket.html", 
                                     ticket_types=ticket_types,
                                     urgency_levels=urgency_levels)

            # Generate unique ticket_id
            while True:
                ticket_id = str(random.randint(1, 9999999999))
                cursor.execute("SELECT ticket_id FROM Tickets WHERE ticket_id = %s", (ticket_id,))
                if not cursor.fetchone():
                    break

            create_date = datetime.now()
            last_update = create_date
            assigner_id = None
            status = "Open"

            # Insert ticket directly with type name and urgency level
            cursor.execute("""
                INSERT INTO Tickets (ticket_id, title, description, type, urgency, 
                                   reporter_id, assigner_id, status, create_date, last_update, 
                                   client_message, dev_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (ticket_id, title, description, ticket_type, urgency, reporter_id, 
                 assigner_id, status, create_date, last_update, "", ""))

            cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'ticket created', reporter_id, create_date, 'ticket was created into the system'))

            conn.commit()
            
            flash("Ticket created successfully!", "success")
            return redirect(url_for('user.user_dashboard'))

        # GET request - render the form with static values
        return render_template("create_ticket.html", 
                             ticket_types=ticket_types,
                             urgency_levels=urgency_levels)
    except Exception as e:
        if request.is_json:
            return jsonify({"message": f"Error creating ticket: {str(e)}"}), 500
        else:
            flash(f"An error occurred: {str(e)}", "error")
            return render_template("create_ticket.html", 
                                 ticket_types=ticket_types,
                                 urgency_levels=urgency_levels)
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
    cursor = conn.cursor(dictionary=True)
    
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