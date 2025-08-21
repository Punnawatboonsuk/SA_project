from flask import Blueprint, render_template, session, redirect, url_for

admin_main_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_main_bp.route('/main')
def main():
    # Check if user is logged in and is an admin
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('login'))
    
    return render_template('admin_main.html', user_id=session.get('user_id'))