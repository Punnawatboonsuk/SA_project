from flask import Flask, render_template, request, redirect, session, jsonify
import bcrypt
import mariadb
import os
from dotenv import load_dotenv
from account_setting_core import account_setting_bp
from user_main_core import user_bp
from staff_main_core import staff_main
# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.register_blueprint(account_setting_bp)
app.register_blueprint(user_bp)
app.register_blueprint(staff_main)
# Connect to MariaDB
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

@app.route('/')
def index():
    return redirect('/login')


# 🔹 Login route (GET/POST)
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password').encode('utf-8')

        if not user_id or not password:
            error = "User ID and password are required."
            return render_template("login.html", error=error)

        # Check selected user_id
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

                session['user_id'] = user['user_id']
                session['username'] = user['username']
                session['role'] = user['role']

                if user['role'] == "Admin":
                    return render_template('admin_main.html',user_id=user['user_id'])
                elif user['role'] == "Staff":
                    return render_template('staff_main.html', user_id=user['user_id'])
                else:
                    return render_template('user_main.html', user_id=user['user_id'])
            else:
                error = "Incorrect password."
        else:
            error = "User not found."

    return render_template("login.html", error=error)


# 🔹 API for dynamic dropdown (AJAX fetch)
@app.route('/api/accounts')
def api_accounts():
    username = request.args.get('username')
    if not username:
        return jsonify([])

    cursor.execute("SELECT user_id, username FROM Accounts WHERE username = %s AND is_banned = 0", (username,))
    accounts = cursor.fetchall()
    return jsonify(accounts)