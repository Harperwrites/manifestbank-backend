from flask import Flask
from backend.app.database import Base, engine
import backend.app.models as models  # <— IMPORTANT: must import so Base can see the models

def create_app():
    app = Flask(__name__)

    # Automatically create tables if they don't exist
    Base.metadata.create_all(bind=engine)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
