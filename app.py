from flask import Flask, render_template, request, redirect, session, jsonify, url_for
import ripbcrypt
import supabase
import os
from dotenv import load_dotenv
import socket
import dns.resolver

def force_custom_dns(hostname):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["8.8.8.8", "1.1.1.1"]  # Google + Cloudflare DNS
    answer = resolver.resolve(hostname, "A")[0]
    return str(answer)

# Override socket.getaddrinfo to use our resolver
_orig_getaddrinfo = socket.getaddrinfo

def custom_getaddrinfo(host, port, *args, **kwargs):
    try:
        ip = force_custom_dns(host)
        return _orig_getaddrinfo(ip, port, *args, **kwargs)
    except Exception:
        return _orig_getaddrinfo(host, port, *args, **kwargs)

socket.getaddrinfo = custom_getaddrinfo

from user_main_core import user_bp
from staff_main_core import staff_bp  # Changed variable name for consistency
from admin_main_core import admin_bp  # You'll need to create this
from mod_main_core import mod_bp      # You'll need to create this
import psycopg2
import psycopg2.extras
# Load environment variables
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
# Register blueprints with appropriate URL prefixes
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(staff_bp, url_prefix='/staff')
app.register_blueprint(admin_bp, url_prefix='/admin')  # Add this blueprint
app.register_blueprint(mod_bp, url_prefix='/mod')      # Add this blueprint

# Database connection function
def get_db_connection():
   return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")

@app.route('/')
def index():
    return redirect('/login')
@app.route('/login')
def login_page():
    return render_template("login.html")

# Login route (GET/POST)
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    user_id = data.get('user_id') 
    password = data.get('password')
    
    if not user_id or not password:
        return jsonify({"message": "User ID and password are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        cursor.execute('SELECT * FROM "Accounts" WHERE user_id = %s', (user_id,))
        user = cursor.fetchone()

        if user:
            if user['account_status'] == 0:
                return jsonify({"message": "This account is banned."}), 403
            elif ripbcrypt.checkpw(password, user['password_hash']):
                # Update password hash
                new_hash = ripbcrypt.hashpw(password, ripbcrypt.gensalt())
                cursor.execute('UPDATE "Accounts" SET password_hash = %s WHERE user_id = %s', (new_hash, user_id))
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
        return url_for('admin.admin_dashboard')
    elif role == "Staff":
        return url_for('staff.staff_main')
    elif role == "Mod":
        return url_for('mod.mod_main')
    else:
        return url_for('user.user_dashboard')

# API for dynamic dropdown (AJAX fetch)
@app.route('/api/accounts')
def api_accounts():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        cursor.execute('SELECT user_id, username FROM "Accounts" WHERE username = %s AND account_status = 1', (username,))
        accounts = cursor.fetchall()
        return jsonify(accounts)
    finally:
        cursor.close()
        conn.close()

@app.route('/logout')
def logout():
    # Clear all session data
    session.clear()
    # Alternatively, remove specific keys
    # session.pop('user_id', None)
    # session.pop('username', None)
    # session.pop('role', None)
    
    return redirect(url_for('login_page'))

if __name__ == '__main__':
    app.run(debug=True)

