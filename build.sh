#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Run migrations, not db.create_all(). create_all() builds tables but never
# executes migrations, so the role and permission seed never ran and
# registration died with "Owner role not found" on every fresh deploy (F-02).
export FLASK_APP="app:create_app"
flask db upgrade
