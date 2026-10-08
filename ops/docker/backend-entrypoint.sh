#!/bin/sh
set -eu

alembic upgrade head
exec uvicorn lcit_sign.app:create_app --factory --host 0.0.0.0 --port 8000
