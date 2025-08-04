# Middleware/api/app.py
from flask import Flask

# This 'app' object will be imported by the API server and all handlers.
# It is instantiated here to prevent circular dependencies.
app = Flask(__name__)

# Ensure jsonify handles unicode correctly without escaping them unnecessarily
app.config['JSON_AS_ASCII'] = False