"""Application Flask — factory minimale."""
import errno
import os
from datetime import timedelta

from flask import Flask, flash, jsonify, redirect, request, url_for

from config import SECRET_KEY, UPLOAD_DIR, DATA_DIR
from database import SessionLocal, bootstrap_app_data
from routes import register_blueprints
from routes.auth import inject_org, inject_notifications


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    bootstrap_app_data()
    register_blueprints(app)

    @app.route('/health')
    def health():
        return jsonify({'status': 'ok'}), 200

    @app.errorhandler(OSError)
    def _handle_os_error(err):
        # Upload multi-part: Werkzeug peut lever OSError(ENOSPC) avant la logique métier.
        if getattr(err, 'errno', None) == errno.ENOSPC:
            msg = (
                "Espace disque insuffisant pour l'import. "
                "Libérez de l'espace sur le disque système (TEMP) puis réessayez."
            )
            try:
                flash(msg)
                if request.method in ('POST', 'PUT', 'PATCH'):
                    return redirect(url_for('upload'))
            except Exception:
                pass
            return msg, 507
        raise err

    @app.context_processor
    def _inject_org():
        return inject_org()

    @app.context_processor
    def _inject_notifications():
        return inject_notifications()

    return app


app = create_app()


if __name__ == '__main__':
    SessionLocal()
    app.run(debug=True, host='0.0.0.0', port=5000)
