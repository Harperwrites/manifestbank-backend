from app.db.session import SessionLocal
from app import crud

def run_seeds():
    db = SessionLocal()
    if not crud.get_user_by_username(db, "harper"):
        u = crud.create_user(db, "harper", "password123")
        crud.create_account(db, u.id, "Main")
    db.close()
    print("Seeds complete")

if __name__ == "__main__":
    run_seeds()
