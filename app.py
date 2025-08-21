from flask import Flask, render_template, request, redirect, session, jsonify, url_for
import bcrypt
import mariadb
import os
from dotenv import load_dotenv
from account_setting_core import account_setting_bp
from user_main_core import user_bp
from staff_main_core import staff_bp  # Changed variable name for consistency
from admin_main_core import admin_bp  # You'll need to create this
from mod_main_core import mod_bp      # You'll need to create this

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Register blueprints with appropriate URL prefixes
app.register_blueprint(account_setting_bp, url_prefix='/account')
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(staff_bp, url_prefix='/staff')
app.register_blueprint(admin_bp, url_prefix='/admin')  # Add this blueprint
app.register_blueprint(mod_bp, url_prefix='/mod')      # Add this blueprint

# Database connection function
def get_db_connection():
    return mariadb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME")
    )

@app.route('/')
def index():
    return redirect('/login')

# Login route (GET/POST)
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password').encode('utf-8')

        if not user_id or not password:
            error = "User ID and password are required."
            return render_template("login.html", error=error)

        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Check if user_id exists
            cursor.execute("SELECT * FROM Accounts WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()

            if user:
                if user['is_banned']:
                    error = "This account is banned."
                elif bcrypt.checkpw(password, user['hashed_password'].encode('utf-8')):
                    # Re-hash password for freshness
                    new_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')
                    cursor.execute("UPDATE Accounts SET hashed_password = %s WHERE user_id = %s", (new_hash, user_id))
                    conn.commit()

                    # Store user info in session
                    session['user_id'] = user['user_id']
                    session['username'] = user['username']
                    session['role'] = user['role']

                    # Redirect based on role
                    if user['role'] == "Admin":
                        return redirect(url_for('admin.main'))  # Redirect to admin blueprint
                    elif user['role'] == "Staff":
                        return redirect(url_for('staff.main'))  # Redirect to staff blueprint
                    elif user['role'] == "Mod":
                        return redirect(url_for('mod.main'))    # Redirect to mod blueprint
                    else:
                        return redirect(url_for('user.main'))   # Redirect to user blueprint
                else:
                    error = "Incorrect password."
            else:
                error = "User not found."
        finally:
            cursor.close()
            conn.close()

    return render_template("login.html", error=error)

# API for dynamic dropdown (AJAX fetch)
@app.route('/api/accounts')
def api_accounts():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT user_id, username FROM Accounts WHERE username = %s AND is_banned = 0", (username,))
        accounts = cursor.fetchall()
        return jsonify(accounts)
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)

@app.route('/logout')
def logout():
    # Clear all session data
    session.clear()
    # Alternatively, remove specific keys
    # session.pop('user_id', None)
    # session.pop('username', None)
    # session.pop('role', None)
    
    return redirect(url_for('login'))