# account_setting_core.py

from flask import Blueprint, request, session, redirect
import bcrypt
import mariadb
import os
from dotenv import load_dotenv

load_dotenv()

account_setting_bp = Blueprint('account_setting', __name__)

# DB connection (can be shared logic later)
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

@account_setting_bp.route('/update_account', methods=['POST'])
def update_account():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    current_password = request.form['current_password'].encode('utf-8')
    new_username = request.form['new_username']
    new_password = request.form['new_password'].encode('utf-8')

    # Fetch current user info
    cursor.execute("SELECT * FROM Accounts WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()

    if not user or not bcrypt.checkpw(current_password, user['hashed_password'].encode('utf-8')):
        return "Incorrect current password", 403

    # Update username
    if new_username and new_username != user['username']:
        cursor.execute("UPDATE Accounts SET username = %s WHERE user_id = %s", (new_username, user_id))
        session['username'] = new_username

    # Update password
    if new_password:
        hashed_pw = bcrypt.hashpw(new_password, bcrypt.gensalt()).decode('utf-8')
        cursor.execute("UPDATE Accounts SET hashed_password = %s WHERE user_id = %s", (hashed_pw, user_id))

    conn.commit()
    return redirect(request.referrer or '/')
