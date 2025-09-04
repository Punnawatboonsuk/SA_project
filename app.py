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
import psycopg2
import psycopg2.extras
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
    conn = psycopg2.connect(
        host=os.getenv("SUPABASE_HOST"),
        database="postgres",        # Supabase default DB
        user="postgres",            # Supabase default user
        password=os.getenv("SUPABASE_DB_PASSWORD"),  # keep password safe
        port="5432"
    )
    return conn

@app.route('/')
def index():
    return redirect('/login')

# Login route (GET/POST)
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    user_id = data.get('username')  # Map frontend's 'username' to backend's 'user_id'
    password = data.get('password').encode('utf-8')
    
    if not user_id or not password:
        return jsonify({"message": "User ID and password are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        cursor.execute("SELECT * FROM Accounts WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()

        if user:
            if user['active_status'] == 0:
                return jsonify({"message": "This account is banned."}), 403
            elif bcrypt.checkpw(password, user['hashed_password'].encode('utf-8')):
                # Update password hash
                new_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')
                cursor.execute("UPDATE Accounts SET hashed_password = %s WHERE user_id = %s", (new_hash, user_id))
                conn.commit()

                # Store user info in session
                session['user_id'] = user['user_id']
                session['username'] = user['username']
                session['role'] = user['role']

                return jsonify({
                    "message": "Login successful",
                    "redirect": get_redirect_url(user['role'])
                }), 200
            else:
                return jsonify({"message": "Incorrect password."}), 401
        else:
            return jsonify({"message": "User not found."}), 404
    finally:
        cursor.close()
        conn.close()

def get_redirect_url(role):
    if role == "Admin":
        return url_for('admin.main')
    elif role == "Staff":
        return url_for('staff.main')
    elif role == "Mod":
        return url_for('mod.main')
    else:
        return url_for('user.main')

# API for dynamic dropdown (AJAX fetch)
@app.route('/api/accounts')
def api_accounts():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
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