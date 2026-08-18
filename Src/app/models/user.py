
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # What the user signs in with, and how they are shown to reviewers.
    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
        index=True
    )

    # The institution's own identifier for this person. Requests are
    # filed against it, so it is taken from the account and never from
    # a form field.
    registration_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    # Display name. Defaults to the username; kept separate so a full
    # name can be recorded later without touching the login.
    name = db.Column(
        db.String(120),
        nullable=False
    )

    # Optional: nothing is emailed yet, and requiring an address would
    # be one more thing to get wrong at registration.
    email = db.Column(
        db.String(150),
        unique=True,
        nullable=True,
        index=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(30),
        nullable=False,
        default="STUDENT"
    )

    department = db.Column(
        db.String(120),
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(
            self.password_hash,
            password
        )

    def __repr__(self):
        return f"<User {self.username}>"
