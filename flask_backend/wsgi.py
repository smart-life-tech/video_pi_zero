"""
WSGI entry point for production deployment (PythonAnywhere, Heroku, etc).
Set this as your WSGI application in your hosting provider's settings.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

from app import create_app
from config import Config, ProductionConfig

# Create the Flask application
config_class = ProductionConfig if os.environ.get('FLASK_ENV') == 'production' else Config
application = create_app(config_class)

if __name__ == '__main__':
    # This is only for development when running directly
    # For production, use gunicorn or app server
    application.run(debug=False)
