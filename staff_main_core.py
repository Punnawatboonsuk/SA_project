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
        # Get filter values from query parameters
        status = request.args.get("status", "")
        urgency = request.args.get("urgency", "")
        type_id = request.args.get("type_id", "")
        search = request.args.get("search", "")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        sort_by = request.args.get("sort_by", "last_update")
        sort_dir = request.args.get("sort_dir", "desc")

        # Validate allowed sort fields to avoid SQL injection
        allowed_sort_fields = ["create_date", "last_update", "title", "status"]
        if sort_by not in allowed_sort_fields:
            sort_by = "last_update"
        if sort_dir.lower() not in ["asc", "desc"]:
            sort_dir = "desc"

        # Build dynamic SQL with filters - only show tickets assigned to current staff
        query = """
            SELECT 
                t.ticket_id, t.title, t.description, t.status, t.create_date, t.last_update,
                tt.type_name, ul.level_name AS urgency,
                ru.username AS reporter_username,
                au.username AS assigner_username
            FROM Tickets t
            JOIN TicketType tt ON t.type = tt.type_id
            LEFT JOIN UrgencyLevel ul ON t.urgency = ul.level_id
            JOIN Accounts ru ON t.reporter_id = ru.user_id
            LEFT JOIN Accounts au ON t.assigner_id = au.user_id
            WHERE t.assigner_id = %s
        """
        params = [user_id]

        if status and status != "all":
            query += " AND t.status = %s"
            params.append(status)

        if urgency and urgency != "all":
            query += " AND ul.level_name = %s"
            params.append(urgency)

        if type_id and type_id != "all":
            query += " AND t.type = %s"
            params.append(type_id)

        if search:
            query += " AND (t.title LIKE %s OR t.description LIKE %s OR ru.username LIKE %s)"
            like_param = f"%{search}%"
            params.extend([like_param, like_param, like_param])

        if start_date:
            query += " AND DATE(t.create_date) >= %s"
            params.append(start_date)

        if end_date:
            query += " AND DATE(t.create_date) <= %s"
            params.append(end_date)

        query += f" ORDER BY t.{sort_by} {sort_dir.upper()}"

        cursor.execute(query, tuple(params))
        tickets = cursor.fetchall()

        # Get ticket types for dropdown
        cursor.execute("SELECT * FROM TicketType")
        ticket_types = cursor.fetchall()

        # Get urgency levels for dropdown
        cursor.execute("SELECT * FROM UrgencyLevel")
        urgency_levels = cursor.fetchall()
        
        # Get status options for dropdown
        cursor.execute("SELECT DISTINCT status FROM Tickets")
        status_options = [row['status'] for row in cursor.fetchall()]

        return render_template(
            "staff_main.html",
            tickets=tickets,
            ticket_types=ticket_types,
            urgency_levels=urgency_levels,
            status_options=status_options,
            username=session.get('username'),
            selected_status=status,
            selected_urgency=urgency,
            selected_type=type_id,
            search_query=search,
            start_date=start_date,
            end_date=end_date,
            sort_by=sort_by,
            sort_dir=sort_dir
        )
    except Exception as e:
        flash(f"Error retrieving tickets: {str(e)}", "error")
        return render_template("staff_main.html", tickets=[], error=str(e))
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
            SELECT t.*, ty.type_name, ul.level_name AS urgency_name,
                   a.username AS reporter_name,
                   b.username AS assigner_name
            FROM Tickets t
            LEFT JOIN TicketType ty ON t.type = ty.type_id
            LEFT JOIN UrgencyLevel ul ON t.urgency = ul.level_id
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
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")

            elif action == "finish":
                cursor.execute("""
                    UPDATE Tickets 
                    SET status = 'in_checking', last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s AND status = 'Assign-working_on'
                """, (now, ticket_id, staff_id))
                if cursor.rowcount > 0:
                    flash("Ticket marked as finished, waiting for review", "success")
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")

            elif action == "reassign":
                cursor.execute("""
                    UPDATE Tickets 
                    SET status = 'Reassigning', last_update = %s 
                    WHERE ticket_id = %s AND assigner_id = %s AND status IN ('Assign-in_queue', 'Assign-working_on')
                """, (now, ticket_id, staff_id))
                if cursor.rowcount > 0:
                    flash("Ticket marked for reassignment", "success")
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
                else:
                    flash("Could not update status. Ticket may have been modified.", "warning")
                    
            conn.commit()
            return redirect(url_for("staff.staff_view_ticket", ticket_id=ticket_id))

        # Determine which buttons to show based on status
        show_work_button = (ticket["status"] == "Assign-in_queue")
        show_finish_button = (ticket["status"] == "Assign-working_on")
        show_reassign_button = (ticket["status"] in ["Assign-in_queue", "Assign-working_on"])
        show_pending_button = True  # Staff can always set to pending

        return render_template(
            "staff_ticket_detail.html",
            ticket=ticket,
            show_work_button=show_work_button,
            show_finish_button=show_finish_button,
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