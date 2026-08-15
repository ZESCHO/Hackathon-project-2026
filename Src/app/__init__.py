from flask import Flask

from app.models import db


def create_app():

    app = Flask(__name__)

    # =====================================================
    # CONFIGURATION
    # =====================================================

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///secure_agentic_ai.db"
    )

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


    # =====================================================
    # INITIALIZE DATABASE
    # =====================================================

    db.init_app(app)


    # =====================================================
    # CREATE DATABASE TABLES
    # =====================================================

    with app.app_context():

        db.create_all()


    return app