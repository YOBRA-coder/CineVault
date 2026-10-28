"""Production entry point (Render, gunicorn, etc.):  gunicorn wsgi:app"""
from app import create_app, start_background

app = create_app()
start_background()
