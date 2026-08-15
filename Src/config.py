import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

# --------------------------------------------------
# PROJECT DIRECTORY
# --------------------------------------------------

BASE_DIR = os.path.abspath(
    os.path.dirname(__file__)
)

# --------------------------------------------------
# DATABASE
# --------------------------------------------------

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "database.db"
)

# Convert Windows path to SQLite-compatible path
DATABASE_URI = "sqlite:///" + DATABASE_PATH.replace("\\", "/")


class Config:

    # --------------------------------------------------
    # FLASK
    # --------------------------------------------------

    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-this"
    )

    # --------------------------------------------------
    # SQLALCHEMY
    # --------------------------------------------------

    SQLALCHEMY_DATABASE_URI = DATABASE_URI

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --------------------------------------------------
    # OPENAI
    # --------------------------------------------------

    AI_API_KEY = os.getenv(
        "AI_API_KEY",
        ""
    )

    AI_MODEL = os.getenv(
        "AI_MODEL",
        "gpt-5.6-luna"
    )