from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import mariadb
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')

# Database connection function
def get_db_connection():
    return mariadb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME")
    )

@staff_bp.route("/staff_main", methods=["GET"])
def staff_main():
    if "user_id" not in session or session.get("role") != "Staff":
        flash("Please log in as staff to access this page", "error")
        return redirect("/login")

    user_id = session["user_id"]
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
            WHERE t.assigner_id = %s
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

@staff_bp.route("/staff_ticket/<ticket_id>", methods=["GET", "POST"])
def staff_view_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Staff":
        flash("Please log in as staff to access this page", "error")
        return redirect("/login")
    
    # Validate ticket_id
    if not ticket_id.isdigit():
        flash("Invalid ticket ID", "error")
        return redirect(url_for('staff.staff_main'))

    staff_id = session.get("user_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # First, get the current ticket details to preserve existing messages
        cursor.execute("""
            SELECT t.*,
                   a.username AS reporter_name,
                   b.username AS assigner_name
            FROM Tickets t
            LEFT JOIN Accounts a ON t.reporter_id = a.user_id
            LEFT JOIN Accounts b ON t.assigner_id = b.user_id
            WHERE t.ticket_id = %s AND t.assigner_id = %s
        """, (ticket_id, staff_id))
        ticket = cursor.fetchone()

        if not ticket:
            flash("Ticket not found or you are not assigned to it", "error")
            return redirect(url_for('staff.staff_main'))

        # Handle form submission
        if request.method == "POST":
            action = request.form.get("action")
            now = datetime.now()
            
            # Get the current values from the database to preserve unchanged messages
            current_client_message = ticket.get("client_message", "")
            current_dev_message = ticket.get("dev_message", "")
            
            # Get new values from form, using current values as defaults if not provided
            client_message = request.form.get("client_message", current_client_message)
            dev_message = request.form.get("dev_message", current_dev_message)

            # Check if messages were actually changed
            messages_changed = (
                client_message != current_client_message or 
                dev_message != current_dev_message
            )

            # Update messages if they were changed or if it's a save action
            if messages_changed or action == "save":
                cursor.execute("""
                    UPDATE Tickets 
                    SET client_message = %s, dev_message = %s, last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s
                """, (client_message, dev_message, now, ticket_id, staff_id))
                conn.commit()
                
                
                if messages_changed:
                    flash("Messages updated successfully", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'update message', staff_id, now, 'Ticket message was updated by staff'))
                else:
                    flash("No changes to messages", "info")

            # Handle status changes
            if action == "work":
                cursor.execute("""
                    UPDATE Tickets 
                    SET status = 'Assign-working_on', last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s AND status = 'Assign-in_queue'
                """, (now, ticket_id, staff_id))
                
                
                if cursor.rowcount > 0:
                    flash("Now working on this ticket", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'working', staff_id, now, 'staff is working on the ticket'))
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")

            elif action == "resolve":
                cursor.execute("""
                    UPDATE Tickets 
                    SET status = 'in_checking', last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s AND status = 'Assign-working_on'
                """, (now, ticket_id, staff_id))
                if cursor.rowcount > 0:
                    flash("Ticket marked as finished, waiting for review", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'resolve', staff_id, now, 'staff resolved the ticket waitnig for user to accept'))
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")

            elif action == "reassign":
                cursor.execute("""
                    UPDATE Tickets 
                    SET status = 'Open', last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s AND status IN ('Assign-in_queue', 'Assign-working_on')
                """, (now, ticket_id, staff_id))
                if cursor.rowcount > 0:
                    flash("Ticket marked for reassignment", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'reassign', staff_id, now, 'the ticket needs reassignation'))
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")
                    
            elif action == "pending":
                cursor.execute("""
                    UPDATE Tickets 
                    SET status = 'Pending', last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s
                """, (now, ticket_id, staff_id))
                if cursor.rowcount > 0:
                    flash("Ticket status set to Pending", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'pending', staff_id, now, 'staff stop working on ticket temporary and gatherig more informations to work'))
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")
                    
            conn.commit()
            return redirect(url_for("staff.staff_view_ticket", ticket_id=ticket_id))

        # Determine which buttons to show based on status
        show_work_button = (ticket["status"] == "Assign-in_queue")
        show_resolve_button = (ticket["status"] == "Assign-working_on")
        show_reassign_button = (ticket["status"] in ["Assign-in_queue", "Assign-working_on"])
        show_pending_button = True  # Staff can always set to pending

        return render_template(
            "staff_ticket_detail.html",
            ticket=ticket,
            show_work_button=show_work_button,
            show_finish_button=show_resolve_button,
            show_reassign_button=show_reassign_button,
            show_pending_button=show_pending_button
        )
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