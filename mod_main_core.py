import os
from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from dotenv import load_dotenv
import mariadb

load_dotenv()

mod_bp = Blueprint('mod', __name__, url_prefix='/mod')

# Database connection function
def get_db_connection():
    return mariadb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME")
    )

@mod_bp.route("/main", methods=["GET"])
def mod_main():
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")
    
    
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
            ORDER BY t.create_date DESC
        """,)
        tickets = cursor.fetchall()

        return render_template(
            "user_main.html",
            tickets=tickets,
            username=session.get('username')
        )
    finally:
        cursor.close()
        conn.close()

@mod_bp.route("/ticket/<ticket_id>", methods=["GET", "POST"])
def mod_view_ticket(ticket_id):
    if "user_id" not in session or session.get("role") != "Mod":
        flash("Please log in as a moderator to access this page", "error")
        return redirect("/login")
    
    # Validate ticket_id
    if not ticket_id.isdigit():
        flash("Invalid ticket ID", "error")
        return redirect(url_for('mod.mod_main'))

    mod_id = session.get("user_id")
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
            WHERE t.ticket_id = %s
        """, (ticket_id,))
        ticket = cursor.fetchone()

        if not ticket:
            flash("Ticket not found", "error")
            return redirect(url_for('mod.mod_main'))

        # Handle form submission
        if request.method == "POST":
            action = request.form.get("action")
            selected_staff_id = request.form.get("selected_staff_id")
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
                    WHERE ticket_id = %s
                """, (client_message, dev_message, now, ticket_id))
                conn.commit()
                
                if messages_changed:
                    flash("Messages updated successfully", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'update message', mod_id, now, 'ticket message was update by mod'))
                else:
                    flash("No changes to messages", "info")

            # Handle status changes and assignments
            if action == "assign" and selected_staff_id:
                cursor.execute("""
                    UPDATE Tickets
                    SET status = 'Assign-in_queue', assigner_id = %s, last_update = %s
                    WHERE ticket_id = %s
                """, (selected_staff_id, now, ticket_id))
                if cursor.rowcount > 0:
                    flash("Ticket assigned successfully", "success")
                    recordmessage = 'ticket was assign to the staff at id : '+ selected_staff_id
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'assigning', mod_id, now, recordmessage))
                else:
                    flash("Could not assign ticket", "warning")

            elif action == "send_upper":
                cursor.execute("""
                    UPDATE Tickets
                    SET status = 'On going to upper level', last_update = %s
                    WHERE ticket_id = %s
                """, (now, ticket_id))
                if cursor.rowcount > 0:
                    flash("Ticket sent to upper level", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'sending upper ', mod_id, now, 'the ticket involve higher level of system in order to resolve'))
                else:
                    flash("Could not update ticket status", "warning")

            elif action == "out_of_service":
                cursor.execute("""
                    UPDATE Tickets
                    SET status = 'Out of service / outsource requirement', last_update = %s
                    WHERE ticket_id = %s
                """, (now, ticket_id))
                if cursor.rowcount > 0:
                    flash("Ticket marked as out of service", "success")
                    cursor.execute("""
                INSERT INTO Transaction_history (ticket_id, action_type, action_by, action_date, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, 'mark as out of service', mod_id, now, 'the ticket is unsolvable or require outernal requirement'))
                else:
                    flash("Could not update ticket status", "warning")
                    
            conn.commit()
            return redirect(url_for("mod.mod_view_ticket", ticket_id=ticket_id))

        matching_staff = []
        if ticket['type'] == 0:
            # For undecided tickets, don't try to match by specialty
            show_matching_staff = False
            flash("This ticket has an undecided type. Showing all available staff.", "info")
        else:
            # For tickets with a specific type, find staff with matching specialties
            show_matching_staff = True
            cursor.execute("""
                SELECT 
                    a.user_id,
                    a.username,
                    GROUP_CONCAT(DISTINCT s.speciality_name ORDER BY s.speciality_name SEPARATOR ', ') AS specialties,
                    COUNT(t2.ticket_id) AS current_assignment_count
                FROM Accounts a
                JOIN StaffSpeciality s ON a.user_id = s.staff_id
                LEFT JOIN Tickets t2 ON a.user_id = t2.assigner_id 
                    AND t2.status NOT IN ('Closed', 'Rejected', 'Resolved')
                WHERE a.role = 'Staff'
                  AND s.speciality_name IN (
                    SELECT tt.type_name 
                    FROM TicketType tt 
                    WHERE tt.type_id = %s
                  )
                GROUP BY a.user_id, a.username
                ORDER BY current_assignment_count ASC
            """, ( ticket['type']))
            matching_staff = cursor.fetchall()

        # Get all staff under this mod with their ticket counts
        cursor.execute("""
            SELECT 
                a.user_id,
                a.username,
                GROUP_CONCAT(DISTINCT s.speciality_name ORDER BY s.speciality_name SEPARATOR ', ') AS specialties,
                COUNT(t2.ticket_id) AS current_assignment_count
            FROM Accounts a
            LEFT JOIN StaffSpeciality s ON a.user_id = s.staff_id
            LEFT JOIN Tickets t2 ON a.user_id = t2.assigner_id 
                AND t2.status NOT IN ('Closed')
            WHERE a.role = 'Staff'
             
            GROUP BY a.user_id, a.username
            ORDER BY current_assignment_count ASC
        """)
        all_staff = cursor.fetchall()

        return render_template(
            "mod_ticket_view.html",
            ticket=ticket,
            matching_staff=matching_staff,
            all_staff=all_staff,
            selected_staff_id=ticket.get('assigner_id')
        )
    except Exception as e:
        flash(f"Error accessing ticket: {str(e)}", "error")
        return redirect(url_for('mod.mod_main'))
    finally:
        cursor.close()
        conn.close()
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
    cursor = conn.cursor(dictionary=True)
    
    try:
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
        return render_template("mod_transaction_history.html", transactions=[], error=str(e))
    finally:
        cursor.close()
        conn.close()