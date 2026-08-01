"""Wipe the database and rebuild it through the migration chain.

Uses migrations rather than db.create_all(). create_all() produces tables but no
alembic_version row and no seed data, so roles and permissions never exist and
registration fails with "Owner role not found" - the same trap that made fresh
deploys impossible (F-02).

Destructive: every row is dropped. Intended for local development only.
"""
import sys

from flask_migrate import upgrade

from app import create_app
from extensions import db

app = create_app()

with app.app_context():
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    shown = uri.split('@')[-1] if '@' in uri else uri
    db_name = shown.rsplit('/', 1)[-1].split('?')[0]
    print(f'This DROPS EVERY TABLE in: {shown}')
    if '--yes' not in sys.argv:
        if input(f'Type "{db_name}" to confirm: ').strip() != db_name:
            print('Aborted.')
            sys.exit(1)

    print('Dropping all tables...')
    db.drop_all()
    db.session.execute(db.text('DROP TABLE IF EXISTS alembic_version'))
    db.session.commit()

    print('Rebuilding through migrations...')
    upgrade()
    print('Done. Roles and permissions are seeded; register a business to begin.')
