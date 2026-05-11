import os

from flask import Flask

import admin
import auth
import buildings
import reisekosten
from db import close_db, init_db


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    init_db()

    app.teardown_appcontext(close_db)

    app.register_blueprint(buildings.bp)
    app.register_blueprint(reisekosten.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)

    @app.context_processor
    def inject_user():
        return {
            'current_user_email': auth.current_user()['email'] if auth.current_user() else None,
            'is_admin': auth.is_admin(),
        }

    return app


if __name__ == '__main__':
    create_app().run(debug=True)
