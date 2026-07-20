# Middleware/api/app.py
from flask import Flask

# This 'app' object will be imported by the API server and all handlers.
# It is instantiated here to prevent circular dependencies.
app = Flask(__name__)

# Ensure jsonify handles unicode correctly without escaping it unnecessarily.
# The legacy JSON_AS_ASCII config key was removed in Flask 2.3; the setting now
# lives on the app's JSON provider, so set it there or non-streaming responses
# still emit \uXXXX escapes.
app.json.ensure_ascii = False