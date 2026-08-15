from flask import Flask

from app.models import db
from app.models.user import User


# =========================================================
# CREATE A SMALL FLASK APP FOR DATABASE ACCESS
# =========================================================

admin_app = Flask(__name__)

admin_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
admin_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(admin_app)


# =========================================================
# CREATE / UPDATE ADMIN ACCOUNT
# =========================================================

with admin_app.app_context():

    db.create_all()

    email = "admin@secureai.com"
    password = "Admin@123"

    admin = User.query.filter_by(
        email=email
    ).first()

    if admin is None:

        admin = User(
            name="System Administrator",
            email=email,
            role="ADMIN",
            is_active=True
        )

        admin.set_password(password)

        db.session.add(admin)
        db.session.commit()

        print()
        print("======================================")
        print("       ADMIN ACCOUNT CREATED")
        print("======================================")
        print("Email    :", email)
        print("Password :", password)
        print("Role     :", admin.role)
        print("======================================")
        print()

    else:

        admin.name = "System Administrator"
        admin.role = "ADMIN"
        admin.is_active = True

        admin.set_password(password)

        db.session.commit()

        print()
        print("======================================")
        print("       ADMIN ACCOUNT UPDATED")
        print("======================================")
        print("Email    :", email)
        print("Password :", password)
        print("Role     :", admin.role)
        print("======================================")
        print()