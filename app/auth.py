import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from db import get_db, now_iso
from mail import send_email

bp = Blueprint('auth', __name__)

TOKEN_TTL_MINUTES = 30


def allowed_domain() -> str:
    return os.environ.get('ALLOWED_EMAIL_DOMAIN', 'tu-berlin.de').lower()


def base_url() -> str:
    return os.environ.get('APP_BASE_URL', '').rstrip('/') or request.host_url.rstrip('/')


def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def is_admin() -> bool:
    return bool(session.get('admin'))


def require_login(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for('auth.login', next=request.path))
        return view(*args, **kwargs)
    return wrapper


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for('admin.login', next=request.path))
        return view(*args, **kwargs)
    return wrapper


def _ensure_user(email: str) -> int:
    db = get_db()
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return row['id']
    cur = db.execute(
        "INSERT INTO users (email, created_at) VALUES (?, ?)",
        (email, now_iso()),
    )
    db.commit()
    return cur.lastrowid


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        domain = allowed_domain()
        if not email or '@' not in email or not email.endswith('@' + domain):
            flash(f'Bitte eine gültige @{domain}-Adresse eingeben.', 'error')
            return render_template('login.html', domain=domain), 400

        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
        db = get_db()
        db.execute(
            "INSERT INTO magic_links (token, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, email, now_iso(), expires.isoformat()),
        )
        db.commit()

        link = base_url() + url_for('auth.verify', token=token)
        send_email(
            to=email,
            subject='Dein Login-Link für das TU Berlin Dashboard',
            body=(
                f'Hallo,\n\nklicke den folgenden Link, um dich anzumelden. '
                f'Der Link ist {TOKEN_TTL_MINUTES} Minuten gültig:\n\n{link}\n\n'
                f'Falls du keinen Login angefordert hast, ignoriere diese E-Mail.'
            ),
        )
        return render_template('message.html',
                               title='Login-Link gesendet',
                               message=f'Wir haben dir einen Login-Link an {email} geschickt. '
                                        'Bitte prüfe dein Postfach.')

    return render_template('login.html', domain=allowed_domain())


@bp.route('/auth/<token>')
def verify(token):
    db = get_db()
    row = db.execute("SELECT * FROM magic_links WHERE token = ?", (token,)).fetchone()
    if not row or row['used']:
        return render_template('message.html',
                               title='Link ungültig',
                               message='Dieser Login-Link ist ungültig oder wurde bereits verwendet. '
                                        'Bitte einen neuen anfordern.'), 400
    expires = datetime.fromisoformat(row['expires_at'])
    if datetime.now(timezone.utc) > expires:
        return render_template('message.html',
                               title='Link abgelaufen',
                               message='Dieser Login-Link ist abgelaufen. Bitte einen neuen anfordern.'), 400

    user_id = _ensure_user(row['email'])
    db.execute("UPDATE magic_links SET used = 1 WHERE token = ?", (token,))
    db.commit()

    session.clear()
    session['user_id'] = user_id
    session['user_email'] = row['email']
    flash('Du bist eingeloggt.', 'success')
    return redirect(url_for('buildings.index'))


@bp.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('user_email', None)
    return redirect(url_for('buildings.index'))
