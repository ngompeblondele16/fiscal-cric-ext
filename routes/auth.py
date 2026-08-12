"""Routes authentification et notifications."""
from flask import flash, redirect, render_template, request, session, url_for

from config import ADMIN_USER
from fiscal_constants import ORGANISATION_NAME, ORGANISATION_SHORT
from database import SessionLocal
from extensions import login_required
from services.admin_auth import (
    request_password_reset,
    reset_password_with_code,
    verify_admin_credentials,
)
from services.email_service import email_configured
from services.notifications import get_recent_notifications, get_unread_count, mark_all_read


def register(app):

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            u = request.form.get('username')
            p = request.form.get('password')
            db = SessionLocal()
            try:
                admin = verify_admin_credentials(db, u, p)
                if admin:
                    session.permanent = bool(request.form.get('remember'))
                    session['user'] = admin.username
                    return redirect(url_for('dashboard'))
            finally:
                db.close()
            flash('Identifiants invalides')
        return render_template('login.html', email_reset_enabled=email_configured())

    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if not email_configured():
            flash('La réinitialisation par email n\'est pas encore configurée. Contactez le support technique.')
            return redirect(url_for('login'))

        if request.method == 'POST':
            email = request.form.get('email', '')
            db = SessionLocal()
            try:
                result = request_password_reset(db, email, request.remote_addr)
                if result.get('error') == 'rate_limit':
                    flash('Trop de demandes. Réessayez dans une heure.')
                elif result.get('error') == 'email_failed':
                    flash('Impossible d\'envoyer l\'email pour le moment. Réessayez plus tard.')
                elif result.get('error') == 'missing_email':
                    flash('Veuillez saisir votre adresse email.')
                else:
                    flash('Si cette adresse est enregistrée, un code vous a été envoyé par email.')
                    session['reset_email'] = email.strip().lower()
                    return redirect(url_for('reset_password'))
            finally:
                db.close()

        return render_template('forgot_password.html')

    @app.route('/reset-password', methods=['GET', 'POST'])
    def reset_password():
        reset_email = session.get('reset_email')
        if not reset_email:
            return redirect(url_for('forgot_password'))

        if request.method == 'POST':
            code = request.form.get('code', '')
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            if password != confirm:
                flash('Les mots de passe ne correspondent pas.')
            else:
                db = SessionLocal()
                try:
                    result = reset_password_with_code(db, reset_email, code, password)
                    if result.get('ok'):
                        session.pop('reset_email', None)
                        flash('Mot de passe mis à jour. Vous pouvez vous connecter.')
                        return redirect(url_for('login'))
                    errors = {
                        'invalid_code': 'Code incorrect.',
                        'expired': 'Code expiré. Demandez un nouveau code.',
                        'weak_password': 'Le mot de passe doit contenir au moins 8 caractères.',
                        'invalid': 'Adresse email invalide.',
                    }
                    flash(errors.get(result.get('error'), 'Réinitialisation impossible.'))
                finally:
                    db.close()

        return render_template('reset_password.html', reset_email=reset_email)

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
    if not session.get('user'):
        return {'app_notifications': [], 'notification_count': 0}
    db = SessionLocal()
    try:
        return {
            'app_notifications': get_recent_notifications(db, limit=15),
            'notification_count': get_unread_count(db),
        }
    finally:
        db.close()
