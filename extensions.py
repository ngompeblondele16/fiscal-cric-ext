"""Extensions Flask partagées (auth, session DB)."""
from functools import wraps

from flask import redirect, session, url_for

from config import ADMIN_USER


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get('user') != ADMIN_USER:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped
