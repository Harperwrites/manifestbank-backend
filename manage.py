import os
from alembic.config import Config
from alembic import command
import click

ALB_CONFIG = Config("alembic.ini")

@click.group()
def cli():
    pass

@cli.command()
def migrate():
    """Run alembic upgrade head"""
    command.upgrade(ALB_CONFIG, "head")
    click.echo("Migrations applied")

@cli.command()
def reset_migrate():
    """Drop DB (dev) and run migrations"""
    # Warning: this is dev-only
    # For postgres you'd drop & recreate the db using psql or createdb
    click.echo("Run DB recreate manually if needed, then run migrate")
    command.upgrade(ALB_CONFIG, "head")

@cli.command()
def send_welcome_messages():
    """Send ManifestBank welcome messages to all existing profiles."""
    from app.db.session import SessionLocal
    from app.services.ether_welcome import send_welcome_messages_to_all

    db = SessionLocal()
    try:
        count = send_welcome_messages_to_all(db)
        click.echo(f"Sent {count} welcome messages")
    finally:
        db.close()

if __name__ == "__main__":
    cli()
