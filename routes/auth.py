"""Routes authentification et notifications."""
from flask import flash, redirect, render_template, request, session, url_for

from config import ADMIN_PASS, ADMIN_USER
from fiscal_constants import ORGANISATION_NAME, ORGANISATION_SHORT
from database import SessionLocal
from extensions import login_required
from services.notifications import get_recent_notifications, get_unread_count, mark_all_read


def register(app):

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            u = request.form.get('username')
            p = request.form.get('password')
            if u == ADMIN_USER and p == ADMIN_PASS:
                session['user'] = u
                return redirect(url_for('dashboard'))
            flash('Identifiants invalides')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/notifications/read', methods=['POST'])
    @login_required
    def notifications_read():
        db = SessionLocal()
        try:
            mark_all_read(db)
            db.commit()
        finally:
            db.close()
        return redirect(request.referrer or url_for('dashboard'))


def inject_org():
    return {
        'organisation_name': ORGANISATION_NAME,
        'organisation_short': ORGANISATION_SHORT,
    }


def inject_notifications():
    if session.get('user') != ADMIN_USER:
        return {'app_notifications': [], 'notification_count': 0}
    db = SessionLocal()
    try:
        return {
            'app_notifications': get_recent_notifications(db, limit=15),
            'notification_count': get_unread_count(db),
        }
    finally:
        db.close()
