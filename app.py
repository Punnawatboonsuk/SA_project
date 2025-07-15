from flask import Flask, render_template, request, redirect, session
import bcrypt
import mariadb
import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") 

# Connect to MariaDB
conn = mariadb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)
cursor = conn.cursor(dictionary=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        # Query user
        cursor.execute("SELECT * FROM Accounts WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user:
            if user['is_banned']:
                error = "This account is banned."
            elif bcrypt.checkpw(password, user['hashed_password'].encode('utf-8')):
                new_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')
                cursor.execute("UPDATE Accounts SET hashed_password = %s WHERE user_id = %s", (new_hash, user['user_id']))
                conn.commit()

                # Session
                session['user_id'] = user['user_id']
                session['username'] = user['username']
                session['role'] = user['role']

                # Redirect to role-specific main page
                if user['role'] == "Admin":
                 return render_template('admin_main.html', username=user['username'])
                elif user['role'] == "Staff":
                 return render_template('staff_main.html', username=user['username'])
                else:
                 return render_template('user_main.html', username=user['username'])

            else:
                error = "Incorrect password."
        else:
            error = "User not found."

    return render_template("login.html", error=error)

@app.route('/')
def index():
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=True)