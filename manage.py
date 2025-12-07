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

if __name__ == "__main__":
    cli()
