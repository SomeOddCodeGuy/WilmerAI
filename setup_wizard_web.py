#!/usr/bin/env python3
"""
WilmerAI Web Setup Wizard

A self-contained Flask web application to help new users configure WilmerAI endpoints.
Run with: python setup_wizard_web.py
Then open http://localhost:5099 in your browser.

This file is intentionally self-contained (HTML templates inline) so it can be
easily deleted if not needed.

This is something small and thrown together quickly with the help of Claude Code,
as I toy with various ideas to try to help make setup a little easier for folks.
Please don't judge me based on this app.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple

try:
    from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
except ImportError:
    print("Error: Flask is required but not installed.")
    print("Please install it with: pip install flask")
    sys.exit(1)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Default configuration (can be overridden by user)
DEFAULT_CONFIG_DIR = "Public/Configs"

# Available API types with descriptions
API_TYPES = [
    ("OllamaApiChat", "Ollama chat API (/api/chat)"),
    ("OllamaApiGenerate", "Ollama completion API (/api/generate)"),
    ("Open-AI-API", "OpenAI-compatible chat API"),
    ("OpenAI-Compatible-Completions", "OpenAI completion API"),
    ("LlamaCppServer", "llama.cpp server"),
    ("KoboldCpp", "KoboldCpp API"),
    ("Claude", "Anthropic Claude API"),
    ("Text-Generation-WebUI", "Text Generation WebUI"),
    ("mlx-lm", "Apple MLX model server"),
]

# All endpoints with descriptions
ENDPOINTS = [
    ("General-Endpoint", "Your best generalist model for main responses"),
    ("General-Fast-Endpoint", "A fast generalist for quick iterations"),
    ("General-Rag-Endpoint", "Best model for handling large context (RAG)"),
    ("General-Rag-Fast-Endpoint", "Fast model for handling large context"),
    ("General-Reasoning-Endpoint", "Model for reasoning tasks"),
    ("Coding-Endpoint", "Your best coding model"),
    ("Coding-Fast-Endpoint", "Fast coding model for iterations"),
    ("Responder-Endpoint", "Model for generating final user responses"),
    ("Thinker-Endpoint", "Model for thinking through problems"),
    ("Worker-Endpoint", "General purpose workhorse model"),
    ("Memory-Generation-Endpoint", "Model for generating conversation summaries"),
    ("Image-Endpoint", "Vision model for processing images"),
]

CONTEXT_SIZES = [(32768, "32K - Standard"), (65536, "64K - Extended")]

# ============================================================================
# HTML Templates (inline for self-containment)
# ============================================================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WilmerAI Setup Wizard</title>
    <style>
        :root {
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --bg-card: #1f2940;
            --accent: #0f3460;
            --accent-light: #e94560;
            --text-primary: #eee;
            --text-secondary: #aaa;
            --border: #2a3a5a;
            --success: #4ade80;
            --input-bg: #0d1525;
            --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2rem;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 2rem;
            margin-bottom: 1.5rem;
        }
        h1 {
            color: var(--accent-light);
            margin-bottom: 0.5rem;
            font-size: 1.8rem;
        }
        h2 {
            color: var(--text-primary);
            margin-bottom: 1rem;
            font-size: 1.3rem;
        }
        h3 {
            color: var(--text-primary);
            font-size: 1.1rem;
        }
        p { color: var(--text-secondary); line-height: 1.6; margin-bottom: 1rem; }
        .subtitle { color: var(--text-secondary); margin-bottom: 2rem; }

        .form-group { margin-bottom: 1.5rem; }
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
            font-weight: 500;
        }
        .label-hint {
            font-weight: normal;
            color: var(--text-secondary);
            font-size: 0.85rem;
        }
        input[type="text"], input[type="url"], select {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--input-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 1rem;
        }
        input:focus, select:focus {
            outline: none;
            border-color: var(--accent-light);
        }
        select { cursor: pointer; }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 0.5rem;
        }
        .checkbox-group input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        .checkbox-group label {
            margin-bottom: 0;
            cursor: pointer;
            color: var(--text-secondary);
        }

        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }
        .btn-primary {
            background: var(--accent-light);
            color: white;
        }
        .btn-primary:hover { opacity: 0.9; }
        .btn-secondary {
            background: var(--accent);
            color: var(--text-primary);
        }
        .btn-secondary:hover { background: #1a4a7a; }
        .btn-small {
            padding: 0.4rem 0.8rem;
            font-size: 0.85rem;
        }
        .btn-danger {
            background: var(--danger);
            color: white;
        }
        .btn-danger:hover { opacity: 0.9; }

        .btn-group {
            display: flex;
            gap: 1rem;
            margin-top: 2rem;
        }

        .mode-cards {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin: 1.5rem 0;
        }
        .mode-card {
            background: var(--bg-secondary);
            border: 2px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }
        .mode-card:hover { border-color: var(--accent-light); }
        .mode-card.selected {
            border-color: var(--accent-light);
            background: var(--accent);
        }
        .mode-card h3 { margin-bottom: 0.5rem; }
        .mode-card p { margin-bottom: 0; font-size: 0.9rem; }

        .progress-bar {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
        }
        .progress-step {
            flex: 1;
            height: 4px;
            background: var(--border);
            border-radius: 2px;
        }
        .progress-step.active { background: var(--accent-light); }
        .progress-step.completed { background: var(--success); }

        .endpoint-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        .endpoint-counter {
            background: var(--accent);
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.85rem;
        }

        .model-list {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            margin: 1rem 0;
        }
        .model-option {
            background: var(--bg-secondary);
            border: 2px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .model-option:hover { border-color: var(--accent-light); background: var(--accent); }
        .model-option .model-info { flex: 1; }
        .model-option .model-name { font-weight: 600; }
        .model-option .model-details { color: var(--text-secondary); font-size: 0.85rem; }
        .model-option .model-actions { display: flex; gap: 0.5rem; }

        .summary-table {
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }
        .summary-table th, .summary-table td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        .summary-table th {
            color: var(--text-secondary);
            font-weight: 500;
            font-size: 0.85rem;
            text-transform: uppercase;
        }
        .summary-table td { color: var(--text-primary); }

        .command-box {
            background: var(--input-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.9rem;
            margin: 1rem 0;
            overflow-x: auto;
        }

        .success-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
        }

        .error-message {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid var(--danger);
            color: var(--danger);
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }

        .divider {
            text-align: center;
            color: var(--text-secondary);
            margin: 1.5rem 0;
            position: relative;
        }
        .divider::before, .divider::after {
            content: '';
            position: absolute;
            top: 50%;
            width: 40%;
            height: 1px;
            background: var(--border);
        }
        .divider::before { left: 0; }
        .divider::after { right: 0; }

        @media (max-width: 600px) {
            .mode-cards { grid-template-columns: 1fr; }
            .btn-group { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="container">
        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

CONFIG_PATH_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="card">
    <h1>Welcome to WilmerAI</h1>
    <p class="subtitle">Setup Wizard</p>

    <p>First, let's locate your WilmerAI configuration folder.</p>

    <div class="form-group">
        <label>Path to Configs folder</label>
        <input type="text" id="config_path" name="config_path"
               value="{{ default_path }}"
               placeholder="e.g., /path/to/WilmerAI/Public/Configs">
    </div>

    {% if error_message %}
    <div class="error-message">{{ error_message }}</div>
    {% endif %}

    {% if validated %}
    <div class="success-message" style="background: rgba(74, 222, 128, 0.1); border: 1px solid var(--success); color: var(--success); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
        Configuration folder validated successfully.
    </div>
    {% endif %}

    <div class="btn-group">
        <button type="button" class="btn btn-secondary" onclick="validatePath()">Validate</button>
        <button type="button" class="btn btn-primary" id="saveBtn" onclick="savePath()" {% if not validated %}disabled style="opacity: 0.5; cursor: not-allowed;"{% endif %}>Continue</button>
    </div>
</div>

<script>
function validatePath() {
    var path = document.getElementById('config_path').value;
    window.location.href = '{{ url_for("validate_config_path") }}?path=' + encodeURIComponent(path);
}

function savePath() {
    var path = document.getElementById('config_path').value;
    window.location.href = '{{ url_for("save_config_path") }}?path=' + encodeURIComponent(path);
}

document.getElementById('config_path').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        validatePath();
    }
});
</script>
{% endblock %}
"""

SELECT_USER_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="progress-bar">
    <div class="progress-step completed"></div>
    <div class="progress-step active"></div>
    <div class="progress-step"></div>
    <div class="progress-step"></div>
</div>

<div class="card">
    <h2>Select User Configuration</h2>
    <p>Choose which user's endpoints you want to configure.</p>

    <form method="POST" action="{{ url_for('save_user_selection') }}">
        <div class="model-list">
            {% for user in users %}
            <div class="model-option" onclick="selectUser('{{ user.id }}')">
                <div class="model-info">
                    <div class="model-name">{{ user.name }}</div>
                    <div class="model-details">{{ user.id }}.json</div>
                </div>
                <input type="radio" name="user_id" value="{{ user.id }}" id="user-{{ user.id }}" style="display:none">
            </div>
            {% endfor %}
        </div>

        <div class="btn-group">
            <a href="{{ url_for('index') }}" class="btn btn-secondary">Back</a>
            <button type="submit" class="btn btn-primary" id="continueBtn" disabled style="opacity: 0.5; cursor: not-allowed;">Continue</button>
        </div>
    </form>
</div>

<script>
var selectedUser = null;

function selectUser(userId) {
    document.querySelectorAll('.model-option').forEach(c => c.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
    document.getElementById('user-' + userId).checked = true;
    selectedUser = userId;

    var btn = document.getElementById('continueBtn');
    btn.disabled = false;
    btn.style.opacity = '1';
    btn.style.cursor = 'pointer';
}
</script>

<style>
.model-option.selected {
    border-color: var(--accent-light);
    background: var(--accent);
}
</style>
{% endblock %}
"""

WIZARD_MODE_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="progress-bar">
    <div class="progress-step completed"></div>
    <div class="progress-step completed"></div>
    <div class="progress-step active"></div>
    <div class="progress-step"></div>
</div>

<div class="card">
    <h2>What would you like to do?</h2>
    <p>Configuring endpoints for: <strong>{{ user_name }}</strong></p>

    <form method="POST" action="{{ url_for('select_wizard_mode') }}">
        <div class="mode-cards">
            <div class="mode-card" onclick="selectMode('new')">
                <h3>New Setup</h3>
                <p>Configure all endpoints from scratch</p>
                <input type="radio" name="wizard_mode" value="new" id="mode-new" style="display:none">
            </div>
            <div class="mode-card" onclick="selectMode('update')">
                <h3>Update Existing</h3>
                <p>View and edit current endpoint settings</p>
                <input type="radio" name="wizard_mode" value="update" id="mode-update" style="display:none">
            </div>
        </div>
        <div class="btn-group">
            <a href="{{ url_for('select_user') }}" class="btn btn-secondary">Back</a>
            <button type="submit" class="btn btn-primary">Continue</button>
        </div>
    </form>
</div>

<script>
function selectMode(mode) {
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
    document.getElementById('mode-' + mode).checked = true;
}
</script>
{% endblock %}
"""

SETUP_MODE_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="progress-bar">
    <div class="progress-step completed"></div>
    <div class="progress-step completed"></div>
    <div class="progress-step completed"></div>
    <div class="progress-step active"></div>
</div>

<div class="card">
    <h2>Setup Mode</h2>
    <p>Configuring endpoints for: <strong>{{ user_name }}</strong></p>

    <p>This wizard will help you configure your LLM endpoints. You'll need to know:</p>
    <ul style="color: var(--text-secondary); margin-left: 1.5rem; margin-bottom: 1.5rem; line-height: 2;">
        <li>Your LLM server's URL and port</li>
        <li>The API type (Ollama, OpenAI, KoboldCpp, etc.)</li>
        <li>Your model name (if applicable)</li>
    </ul>

    <h3>How many LLMs will you be using?</h3>

    <form method="POST" action="{{ url_for('select_mode') }}">
        <div class="mode-cards">
            <div class="mode-card" onclick="selectMode('single')">
                <h3>One Model</h3>
                <p>Use the same model for all endpoints</p>
                <input type="radio" name="mode" value="single" id="mode-single" style="display:none">
            </div>
            <div class="mode-card" onclick="selectMode('multiple')">
                <h3>Multiple Models</h3>
                <p>Configure each endpoint individually</p>
                <input type="radio" name="mode" value="multiple" id="mode-multiple" style="display:none">
            </div>
        </div>
        <div class="btn-group">
            <a href="{{ url_for('wizard_mode') }}" class="btn btn-secondary">Back</a>
            <button type="submit" class="btn btn-primary">Continue</button>
        </div>
    </form>
</div>

<script>
function selectMode(mode) {
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
    document.getElementById('mode-' + mode).checked = true;
}
</script>
{% endblock %}
"""

SINGLE_MODEL_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="progress-bar">
    <div class="progress-step completed"></div>
    <div class="progress-step active"></div>
    <div class="progress-step"></div>
</div>

<div class="card">
    <h2>Configure Your Model</h2>
    <p>This configuration will be applied to all 12 endpoints.</p>

    <form method="POST" action="{{ url_for('save_single_model') }}">
        <div class="form-group">
            <label>API Type</label>
            <select name="api_type" required>
                {% for api_type, description in api_types %}
                <option value="{{ api_type }}" {% if api_type == current_config.api_type %}selected{% endif %}>
                    {{ api_type }} - {{ description }}
                </option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label>
                Endpoint URL
                <span class="label-hint">(e.g., http://127.0.0.1:11434)</span>
            </label>
            <input type="url" name="endpoint_url" value="{{ current_config.endpoint_url }}" required>
        </div>

        <div class="form-group">
            <label>
                Model Name
                <span class="label-hint">(e.g., qwen2.5:32b, llama3:8b)</span>
            </label>
            <input type="text" name="model_name" id="model_name"
                   value="{{ current_config.model_name }}"
                   placeholder="Enter model name"
                   {% if current_config.dont_include_model %}disabled{% endif %}>
            <div class="checkbox-group">
                <input type="checkbox" name="no_model_name" id="no_model_name"
                       onchange="toggleModelName()"
                       {% if current_config.dont_include_model %}checked{% endif %}>
                <label for="no_model_name">Don't send model name to API</label>
            </div>
        </div>

        <div class="form-group">
            <label>Context Size</label>
            <select name="context_size">
                {% for size, label in context_sizes %}
                <option value="{{ size }}" {% if size == current_config.context_size %}selected{% endif %}>
                    {{ label }}
                </option>
                {% endfor %}
            </select>
        </div>

        <div class="btn-group">
            <a href="{{ url_for('index') }}" class="btn btn-secondary">Back</a>
            <button type="submit" class="btn btn-primary">Apply to All Endpoints</button>
        </div>
    </form>
</div>

<script>
function toggleModelName() {
    var checkbox = document.getElementById('no_model_name');
    var input = document.getElementById('model_name');
    input.disabled = checkbox.checked;
    if (checkbox.checked) input.value = '';
}
</script>
{% endblock %}
"""

MULTIPLE_ENDPOINT_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="progress-bar">
    <div class="progress-step completed"></div>
    <div class="progress-step active"></div>
    <div class="progress-step"></div>
</div>

<div class="card">
    <div class="endpoint-header">
        <div>
            <h2>{{ endpoint_name }}</h2>
            <p style="margin-bottom: 0;">{{ endpoint_description }}</p>
        </div>
        <span class="endpoint-counter">{{ current }} / {{ total }}</span>
    </div>

    {% if error_message %}
    <div class="error-message">{{ error_message }}</div>
    {% endif %}

    {% if saved_models %}
    <h3 style="margin: 1.5rem 0 0.5rem;">Load from saved model:</h3>
    <p style="font-size: 0.9rem;">Click a model to fill in the form below. You can then modify and save.</p>
    <div class="model-list">
        {% for model in saved_models %}
        <div class="model-option" onclick="fillFromModel({{ loop.index0 }})">
            <div class="model-info">
                <div class="model-name">{{ model.name }}</div>
                <div class="model-details">{{ model.api_type }} @ {{ model.endpoint_url }}{% if model.model_name %} ({{ model.model_name }}){% endif %}</div>
            </div>
            <div class="model-actions">
                <button type="button" class="btn btn-small btn-danger" onclick="event.stopPropagation(); deleteModel({{ loop.index0 }})">Delete</button>
            </div>
        </div>
        {% endfor %}
    </div>
    <div class="divider">or configure manually</div>
    {% endif %}

    <form method="POST" action="{{ url_for('save_endpoint', index=current-1) }}" id="configForm">
        <div class="form-group">
            <label>API Type</label>
            <select name="api_type" id="api_type">
                {% for api_type, description in api_types %}
                <option value="{{ api_type }}" {% if api_type == current_config.api_type %}selected{% endif %}>
                    {{ api_type }} - {{ description }}
                </option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label>Endpoint URL</label>
            <input type="url" name="endpoint_url" id="endpoint_url" value="{{ current_config.endpoint_url }}">
        </div>

        <div class="form-group">
            <label>Model Name</label>
            <input type="text" name="model_name" id="model_name"
                   value="{{ current_config.model_name }}"
                   placeholder="Enter model name"
                   {% if current_config.dont_include_model %}disabled{% endif %}>
            <div class="checkbox-group">
                <input type="checkbox" name="no_model_name" id="no_model_name"
                       onchange="toggleModelName()"
                       {% if current_config.dont_include_model %}checked{% endif %}>
                <label for="no_model_name">Don't send model name to API</label>
            </div>
        </div>

        <div class="form-group">
            <label>Context Size</label>
            <select name="context_size" id="context_size">
                {% for size, label in context_sizes %}
                <option value="{{ size }}" {% if size == current_config.context_size %}selected{% endif %}>
                    {{ label }}
                </option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label>
                Save as model named
                <span class="label-hint">(for reuse on other endpoints)</span>
            </label>
            <input type="text" name="model_display_name" id="model_display_name"
                   value="{{ current_config.name }}"
                   placeholder="e.g., My Qwen 32B">
        </div>

        <div class="btn-group">
            {% if current > 1 %}
            <a href="{{ url_for('configure_endpoint', index=current-2) }}" class="btn btn-secondary">Back</a>
            {% else %}
            <a href="{{ url_for('index') }}" class="btn btn-secondary">Back</a>
            {% endif %}
            <button type="submit" class="btn btn-primary">
                {% if current == total %}Finish{% else %}Next Endpoint{% endif %}
            </button>
        </div>
    </form>
</div>

<script>
var savedModels = {{ saved_models_json | safe }};

function fillFromModel(index) {
    var model = savedModels[index];
    document.getElementById('api_type').value = model.api_type;
    document.getElementById('endpoint_url').value = model.endpoint_url;
    document.getElementById('model_name').value = model.model_name;
    document.getElementById('context_size').value = model.context_size;
    document.getElementById('model_display_name').value = model.name;

    var checkbox = document.getElementById('no_model_name');
    checkbox.checked = model.dont_include_model;
    document.getElementById('model_name').disabled = model.dont_include_model;
}

function toggleModelName() {
    var checkbox = document.getElementById('no_model_name');
    var input = document.getElementById('model_name');
    input.disabled = checkbox.checked;
    if (checkbox.checked) input.value = '';
}

function deleteModel(index) {
    if (confirm('Delete this saved model? This only removes it from the saved list, not from any endpoints already configured.')) {
        window.location.href = '{{ url_for("delete_model", index=current-1) }}?model_index=' + index;
    }
}
</script>
{% endblock %}
"""

COMPLETE_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="progress-bar">
    <div class="progress-step completed"></div>
    <div class="progress-step completed"></div>
    <div class="progress-step completed"></div>
    {% if not is_update_mode %}<div class="progress-step completed"></div>{% endif %}
</div>

{% if not is_update_mode %}
<div class="card" style="text-align: center;">
    <div class="success-icon">&#10004;</div>
    <h1 style="color: var(--success);">Configuration Complete!</h1>
    <p>All endpoints have been configured successfully.</p>
</div>
{% endif %}

<div class="card">
    <h2>Endpoint Configuration{% if is_update_mode %} for {{ user_name }}{% else %} Summary{% endif %}</h2>
    <table class="summary-table">
        <thead>
            <tr>
                <th style="width: 50px;"></th>
                <th>Endpoint</th>
                <th>Model</th>
                <th>API Type</th>
            </tr>
        </thead>
        <tbody>
            {% for endpoint, config in assignments.items() %}
            <tr>
                <td><a href="{{ url_for('edit_endpoint', endpoint_name=endpoint) }}" class="btn btn-small btn-secondary">Edit</a></td>
                <td>{{ endpoint }}</td>
                <td>{{ config.name or config.model_name or '(no model)' }}</td>
                <td>{{ config.api_type }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div class="card">
    <h2>Start WilmerAI</h2>
    <p>Run the appropriate command for your platform:</p>

    <div style="display: grid; gap: 0.75rem; margin: 1rem 0;">
        <div class="command-box" style="margin: 0;">
            <strong>Windows:</strong> run_windows.bat --ConfigDirectory "{{ config_dir }}" --User "{{ user_id }}"
        </div>
        <div class="command-box" style="margin: 0;">
            <strong>macOS:</strong> bash run_macos.sh --ConfigDirectory "{{ config_dir }}" --User "{{ user_id }}"
        </div>
        <div class="command-box" style="margin: 0;">
            <strong>Linux:</strong> bash run_linux.sh --ConfigDirectory "{{ config_dir }}" --User "{{ user_id }}"
        </div>
    </div>

    <p style="color: var(--text-secondary); font-size: 0.9rem;">
        Or run the Python script directly: <code>python server.py --ConfigDirectory "{{ config_dir }}" --User "{{ user_id }}"</code>
    </p>

    <div class="btn-group" style="justify-content: center;">
        <a href="{{ url_for('wizard_mode') }}" class="btn btn-secondary">Back</a>
        <a href="{{ url_for('index') }}" class="btn btn-secondary">Start Over</a>
    </div>
</div>
{% endblock %}
"""

EDIT_ENDPOINT_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="card">
    <div class="endpoint-header">
        <div>
            <h2>Edit: {{ endpoint_name }}</h2>
            <p style="margin-bottom: 0;">{{ endpoint_description }}</p>
        </div>
    </div>

    {% if saved_models %}
    <h3 style="margin: 1.5rem 0 0.5rem;">Load from saved model:</h3>
    <p style="font-size: 0.9rem;">Click a model to fill in the form below.</p>
    <div class="model-list">
        {% for model in saved_models %}
        <div class="model-option" onclick="fillFromModel({{ loop.index0 }})">
            <div class="model-info">
                <div class="model-name">{{ model.name }}</div>
                <div class="model-details">{{ model.api_type }} @ {{ model.endpoint_url }}{% if model.model_name %} ({{ model.model_name }}){% endif %}</div>
            </div>
        </div>
        {% endfor %}
    </div>
    <div class="divider">or configure manually</div>
    {% endif %}

    <form method="POST" action="{{ url_for('save_edit_endpoint', endpoint_name=endpoint_name) }}">
        <div class="form-group">
            <label>API Type</label>
            <select name="api_type" id="api_type">
                {% for api_type, description in api_types %}
                <option value="{{ api_type }}" {% if api_type == current_config.api_type %}selected{% endif %}>
                    {{ api_type }} - {{ description }}
                </option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label>Endpoint URL</label>
            <input type="url" name="endpoint_url" id="endpoint_url" value="{{ current_config.endpoint_url }}">
        </div>

        <div class="form-group">
            <label>Model Name</label>
            <input type="text" name="model_name" id="model_name"
                   value="{{ current_config.model_name }}"
                   placeholder="Enter model name"
                   {% if current_config.dont_include_model %}disabled{% endif %}>
            <div class="checkbox-group">
                <input type="checkbox" name="no_model_name" id="no_model_name"
                       onchange="toggleModelName()"
                       {% if current_config.dont_include_model %}checked{% endif %}>
                <label for="no_model_name">Don't send model name to API</label>
            </div>
        </div>

        <div class="form-group">
            <label>Context Size</label>
            <select name="context_size" id="context_size">
                {% for size, label in context_sizes %}
                <option value="{{ size }}" {% if size == current_config.context_size %}selected{% endif %}>
                    {{ label }}
                </option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label>
                Display Name
                <span class="label-hint">(for identification)</span>
            </label>
            <input type="text" name="model_display_name" id="model_display_name"
                   value="{{ current_config.name }}"
                   placeholder="e.g., My Qwen 32B">
        </div>

        <div class="btn-group">
            <a href="{{ url_for('complete') }}" class="btn btn-secondary">Cancel</a>
            <button type="submit" class="btn btn-primary">Save Changes</button>
        </div>
    </form>
</div>

<script>
var savedModels = {{ saved_models_json | safe }};

function fillFromModel(index) {
    var model = savedModels[index];
    document.getElementById('api_type').value = model.api_type;
    document.getElementById('endpoint_url').value = model.endpoint_url;
    document.getElementById('model_name').value = model.model_name;
    document.getElementById('context_size').value = model.context_size;
    document.getElementById('model_display_name').value = model.name;

    var checkbox = document.getElementById('no_model_name');
    checkbox.checked = model.dont_include_model;
    document.getElementById('model_name').disabled = model.dont_include_model;
}

function toggleModelName() {
    var checkbox = document.getElementById('no_model_name');
    var input = document.getElementById('model_name');
    input.disabled = checkbox.checked;
    if (checkbox.checked) input.value = '';
}
</script>
{% endblock %}
"""


# ============================================================================
# Helper Functions
# ============================================================================

@dataclass
class ModelConfig:
    """
    Configuration data for an LLM endpoint.

    Attributes:
        name: Display name for the endpoint (used in UI and file naming).
        api_type: The API type configuration file name (e.g., 'OllamaApiChat').
        endpoint_url: The URL of the LLM server endpoint.
        model_name: The model name to send to the API.
        context_size: Maximum context token size for the model.
        dont_include_model: If True, the model name is not sent to the API.
    """
    name: str
    api_type: str
    endpoint_url: str
    model_name: str
    context_size: int
    dont_include_model: bool


def render(template_name, **kwargs):
    """Render a template with the base template."""
    templates = {
        'base': BASE_TEMPLATE,
        'config_path': CONFIG_PATH_TEMPLATE,
        'select_user': SELECT_USER_TEMPLATE,
        'wizard_mode': WIZARD_MODE_TEMPLATE,
        'setup_mode': SETUP_MODE_TEMPLATE,
        'single_model': SINGLE_MODEL_TEMPLATE,
        'multiple_endpoint': MULTIPLE_ENDPOINT_TEMPLATE,
        'complete': COMPLETE_TEMPLATE,
        'edit_endpoint': EDIT_ENDPOINT_TEMPLATE,
    }

    base = templates['base']
    content = templates[template_name]

    block_match = re.search(r'{%\s*block\s+content\s*%}(.*?){%\s*endblock\s*%}', content, re.DOTALL)
    if block_match:
        block_content = block_match.group(1)
        final = base.replace('{% block content %}{% endblock %}', block_content)
        return render_template_string(final, **kwargs)

    return render_template_string(content, **kwargs)


def get_endpoints_dir() -> str:
    """Get the endpoints directory for the current user."""
    config_dir = session.get('config_dir', DEFAULT_CONFIG_DIR)
    user_id = session.get('user_id', '_example_general_workflow')

    # Load user config to get endpoints folder
    user_file = os.path.join(config_dir, "Users", f"{user_id}.json")
    try:
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        # The field is called endpointConfigsSubDirectory in user configs
        endpoints_folder = user_data.get('endpointConfigsSubDirectory', user_id)
    except Exception:
        endpoints_folder = user_id

    return os.path.join(config_dir, "Endpoints", endpoints_folder)


def validate_config_dir(path: str) -> Tuple[bool, str]:
    """
    Validate that the given path is a valid WilmerAI Configs directory.
    Returns (is_valid, error_message).
    """
    if not os.path.exists(path):
        return False, f"Path does not exist: {path}"

    if not os.path.isdir(path):
        return False, f"Path is not a directory: {path}"

    # Check for required subdirectories
    required_dirs = ['Endpoints', 'Users', 'ApiTypes']
    missing = []
    for subdir in required_dirs:
        if not os.path.isdir(os.path.join(path, subdir)):
            missing.append(subdir)

    if missing:
        return False, f"Cannot find required folder(s): {', '.join(missing)}"

    return True, ""


def load_users(config_dir: str) -> List[Dict]:
    """
    Load all user configurations from the Users folder.
    Excludes _current-user.json.
    """
    users_dir = os.path.join(config_dir, "Users")
    users = []

    try:
        for filename in sorted(os.listdir(users_dir)):
            if not filename.endswith('.json'):
                continue
            if filename == '_current-user.json':
                continue

            user_id = filename[:-5]  # Remove .json
            filepath = os.path.join(users_dir, filename)

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                user_name = data.get('userName', user_id)
            except Exception:
                user_name = user_id

            users.append({
                'id': user_id,
                'name': user_name
            })
    except Exception as e:
        print(f"Error loading users: {e}")

    return users


def get_available_endpoints() -> List[Tuple[str, str]]:
    """
    Get available endpoints from the user's endpoint folder.
    Returns list of (endpoint_name, description) tuples.
    """
    endpoints_dir = get_endpoints_dir()
    available = []

    # Map of known endpoints to descriptions
    endpoint_descriptions = {name: desc for name, desc in ENDPOINTS}

    try:
        for filename in sorted(os.listdir(endpoints_dir)):
            if not filename.endswith('.json'):
                continue
            endpoint_name = filename[:-5]  # Remove .json
            description = endpoint_descriptions.get(endpoint_name, "Custom endpoint")
            available.append((endpoint_name, description))
    except Exception as e:
        print(f"Error scanning endpoints dir {endpoints_dir}: {e}")

    return available


def load_endpoint_config(endpoint_name: str) -> Optional[ModelConfig]:
    """Load configuration from an endpoint JSON file."""
    endpoints_dir = get_endpoints_dir()
    filepath = os.path.join(endpoints_dir, f"{endpoint_name}.json")

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return ModelConfig(
            name=data.get('modelNameForDisplayOnly', ''),
            api_type=data.get('apiTypeConfigFileName', 'OllamaApiChat'),
            endpoint_url=data.get('endpoint', 'http://127.0.0.1:11434'),
            model_name=data.get('modelNameToSendToAPI', ''),
            context_size=data.get('maxContextTokenSize', 32768),
            dont_include_model=data.get('dontIncludeModel', False)
        )
    except Exception as e:
        print(f"Error loading {endpoint_name}: {e}")
        return None


def load_all_unique_models() -> List[Dict]:
    """Load all endpoint configs and return unique model configurations."""
    seen_configs = {}  # key: (api_type, endpoint_url, model_name, context_size) -> config

    available_endpoints = get_available_endpoints()
    for endpoint_name, _ in available_endpoints:
        config = load_endpoint_config(endpoint_name)
        if config and config.name:  # Only include configs with a display name
            key = (config.api_type, config.endpoint_url, config.model_name, config.context_size)
            if key not in seen_configs:
                seen_configs[key] = asdict(config)

    return list(seen_configs.values())


def update_endpoint_file(endpoint_name: str, config: ModelConfig) -> bool:
    """Update an endpoint JSON file with the new configuration."""
    endpoints_dir = get_endpoints_dir()
    filepath = os.path.join(endpoints_dir, f"{endpoint_name}.json")

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        data['endpoint'] = config.endpoint_url
        data['apiTypeConfigFileName'] = config.api_type
        data['maxContextTokenSize'] = config.context_size
        data['modelNameToSendToAPI'] = config.model_name
        data['modelNameForDisplayOnly'] = config.name
        data['dontIncludeModel'] = config.dont_include_model

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return True
    except Exception as e:
        print(f"Error updating {endpoint_name}: {e}")
        return False


def get_default_config() -> ModelConfig:
    """Return a default configuration."""
    return ModelConfig(
        name='',
        api_type='OllamaApiChat',
        endpoint_url='http://127.0.0.1:11434',
        model_name='',
        context_size=32768,
        dont_include_model=False
    )


# ============================================================================
# Routes
# ============================================================================

@app.route('/')
def index():
    """Config path entry page."""
    session.clear()
    default_path = os.path.abspath(DEFAULT_CONFIG_DIR)
    return render('config_path', default_path=default_path, validated=False)


@app.route('/validate-config')
def validate_config_path():
    """Validate the config path."""
    path = request.args.get('path', '').strip()
    is_valid, error_msg = validate_config_dir(path)

    if is_valid:
        session['validated_path'] = path
        return render('config_path', default_path=path, validated=True)
    else:
        return render('config_path', default_path=path, validated=False, error_message=error_msg)


@app.route('/save-config')
def save_config_path():
    """Save the config path and proceed to user selection."""
    path = request.args.get('path', '').strip()

    # Re-validate just to be safe
    is_valid, error_msg = validate_config_dir(path)
    if not is_valid:
        return render('config_path', default_path=path, validated=False, error_message=error_msg)

    session['config_dir'] = path
    return redirect(url_for('select_user'))


@app.route('/select-user')
def select_user():
    """User selection page."""
    config_dir = session.get('config_dir', DEFAULT_CONFIG_DIR)
    users = load_users(config_dir)

    if not users:
        return render('config_path',
                      default_path=config_dir,
                      validated=False,
                      error_message="No user configurations found in the Users folder.")

    return render('select_user', users=users)


@app.route('/save-user', methods=['POST'])
def save_user_selection():
    """Save the selected user and proceed to wizard mode selection."""
    user_id = request.form.get('user_id', '')
    if not user_id:
        return redirect(url_for('select_user'))

    session['user_id'] = user_id

    # Get user display name
    config_dir = session.get('config_dir', DEFAULT_CONFIG_DIR)
    user_file = os.path.join(config_dir, "Users", f"{user_id}.json")
    try:
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        session['user_name'] = user_data.get('userName', user_id)
    except Exception:
        session['user_name'] = user_id

    return redirect(url_for('wizard_mode'))


@app.route('/wizard-mode')
def wizard_mode():
    """Wizard mode selection page (new setup vs update existing)."""
    user_name = session.get('user_name', 'Unknown User')
    return render('wizard_mode', user_name=user_name)


@app.route('/select-wizard-mode', methods=['POST'])
def select_wizard_mode():
    """Handle wizard mode selection."""
    wizard_mode_choice = request.form.get('wizard_mode', 'new')
    session['wizard_mode'] = wizard_mode_choice

    if wizard_mode_choice == 'update':
        # Go directly to the summary/edit table
        return redirect(url_for('complete'))
    else:
        # Go to setup mode (single vs multiple)
        return redirect(url_for('setup_mode'))


@app.route('/setup-mode')
def setup_mode():
    """Setup mode page (single vs multiple models)."""
    user_name = session.get('user_name', 'Unknown User')
    return render('setup_mode', user_name=user_name)


@app.route('/select-mode', methods=['POST'])
def select_mode():
    """Handle single/multiple mode selection."""
    mode = request.form.get('mode', 'single')
    session['mode'] = mode
    session['assignments'] = {}

    # Load existing unique models from endpoint files
    session['saved_models'] = load_all_unique_models()

    if mode == 'single':
        return redirect(url_for('single_model'))
    else:
        return redirect(url_for('configure_endpoint', index=0))


@app.route('/single-model')
def single_model():
    """Single model configuration page."""
    # Load current config from first endpoint as starting point
    current_config = load_endpoint_config(ENDPOINTS[0][0]) or get_default_config()

    return render('single_model',
                  api_types=API_TYPES,
                  context_sizes=CONTEXT_SIZES,
                  current_config=asdict(current_config))


@app.route('/save-single-model', methods=['POST'])
def save_single_model():
    """Save single model configuration to all endpoints."""
    config = ModelConfig(
        name="All Endpoints",
        api_type=request.form['api_type'],
        endpoint_url=request.form['endpoint_url'],
        model_name=request.form.get('model_name', ''),
        context_size=int(request.form['context_size']),
        dont_include_model='no_model_name' in request.form
    )

    available_endpoints = get_available_endpoints()
    assignments = {}
    for endpoint_name, _ in available_endpoints:
        update_endpoint_file(endpoint_name, config)
        assignments[endpoint_name] = asdict(config)

    session['assignments'] = assignments
    return redirect(url_for('complete'))


@app.route('/endpoint/<int:index>')
def configure_endpoint(index):
    """Configure a specific endpoint."""
    available_endpoints = get_available_endpoints()

    if index >= len(available_endpoints):
        return redirect(url_for('complete'))

    endpoint_name, endpoint_desc = available_endpoints[index]
    saved_models = session.get('saved_models', [])
    error_message = session.pop('error_message', None)

    # Load current config from the endpoint file
    current_config = load_endpoint_config(endpoint_name) or get_default_config()

    return render('multiple_endpoint',
                  endpoint_name=endpoint_name,
                  endpoint_description=endpoint_desc,
                  current=index + 1,
                  total=len(available_endpoints),
                  saved_models=saved_models,
                  saved_models_json=json.dumps(saved_models),
                  current_config=asdict(current_config),
                  api_types=API_TYPES,
                  context_sizes=CONTEXT_SIZES,
                  error_message=error_message)


@app.route('/save-endpoint/<int:index>', methods=['POST'])
def save_endpoint(index):
    """Save configuration for a specific endpoint."""
    available_endpoints = get_available_endpoints()
    endpoint_name, _ = available_endpoints[index]
    saved_models = session.get('saved_models', [])
    assignments = session.get('assignments', {})

    model_name = request.form.get('model_name', '')
    display_name = request.form.get('model_display_name', '').strip()

    # Generate a display name if not provided
    if not display_name:
        display_name = model_name.split(':')[0].title() if model_name else request.form['api_type']

    config = ModelConfig(
        name=display_name,
        api_type=request.form['api_type'],
        endpoint_url=request.form['endpoint_url'],
        model_name=model_name,
        context_size=int(request.form['context_size']),
        dont_include_model='no_model_name' in request.form
    )

    # Check if this is a new unique configuration
    config_key = (config.api_type, config.endpoint_url, config.model_name, config.context_size)
    existing_names = {m['name'] for m in saved_models}
    existing_keys = {(m['api_type'], m['endpoint_url'], m['model_name'], m['context_size']) for m in saved_models}

    # Check for name conflict with different config
    name_conflict = False
    for m in saved_models:
        if m['name'] == display_name:
            m_key = (m['api_type'], m['endpoint_url'], m['model_name'], m['context_size'])
            if m_key != config_key:
                name_conflict = True
                break

    if name_conflict:
        session['error_message'] = f'A saved model named "{display_name}" already exists with different settings. Please choose a different name.'
        return redirect(url_for('configure_endpoint', index=index))

    # Add to saved models if it's a new configuration
    if config_key not in existing_keys:
        saved_models.append(asdict(config))
        session['saved_models'] = saved_models
    elif display_name not in existing_names:
        # Same config but new name - update the existing entry
        for m in saved_models:
            m_key = (m['api_type'], m['endpoint_url'], m['model_name'], m['context_size'])
            if m_key == config_key:
                m['name'] = display_name
                break
        session['saved_models'] = saved_models

    # Update the endpoint file
    update_endpoint_file(endpoint_name, config)
    assignments[endpoint_name] = asdict(config)
    session['assignments'] = assignments

    # Move to next endpoint or complete
    if index + 1 >= len(available_endpoints):
        return redirect(url_for('complete'))
    else:
        return redirect(url_for('configure_endpoint', index=index + 1))


@app.route('/delete-model/<int:index>')
def delete_model(index):
    """Delete a saved model."""
    model_index = request.args.get('model_index', type=int)
    saved_models = session.get('saved_models', [])

    if model_index is not None and 0 <= model_index < len(saved_models):
        saved_models.pop(model_index)
        session['saved_models'] = saved_models

    return redirect(url_for('configure_endpoint', index=index))


@app.route('/complete')
def complete():
    """Completion page showing summary."""
    assignments = session.get('assignments', {})
    user_id = session.get('user_id', '_example_general_workflow')
    user_name = session.get('user_name', user_id)
    config_dir = session.get('config_dir', DEFAULT_CONFIG_DIR)
    is_update_mode = session.get('wizard_mode') == 'update'

    # Get available endpoints from the user's folder
    available_endpoints = get_available_endpoints()

    # If no assignments in session, load from files
    if not assignments:
        for endpoint_name, _ in available_endpoints:
            config = load_endpoint_config(endpoint_name)
            if config:
                assignments[endpoint_name] = asdict(config)

    return render('complete',
                  assignments=assignments,
                  user_id=user_id,
                  user_name=user_name,
                  config_dir=config_dir,
                  is_update_mode=is_update_mode)


@app.route('/edit/<endpoint_name>')
def edit_endpoint(endpoint_name):
    """Edit a specific endpoint from the summary page."""
    # Find the endpoint description
    endpoint_desc = ""
    for name, desc in ENDPOINTS:
        if name == endpoint_name:
            endpoint_desc = desc
            break

    if not endpoint_desc:
        return redirect(url_for('complete'))

    # Load saved models for the picker
    saved_models = session.get('saved_models', [])
    if not saved_models:
        saved_models = load_all_unique_models()
        session['saved_models'] = saved_models

    # Load current config from the endpoint file
    current_config = load_endpoint_config(endpoint_name) or get_default_config()

    return render('edit_endpoint',
                  endpoint_name=endpoint_name,
                  endpoint_description=endpoint_desc,
                  saved_models=saved_models,
                  saved_models_json=json.dumps(saved_models),
                  current_config=asdict(current_config),
                  api_types=API_TYPES,
                  context_sizes=CONTEXT_SIZES)


@app.route('/save-edit/<endpoint_name>', methods=['POST'])
def save_edit_endpoint(endpoint_name):
    """Save changes to a specific endpoint and return to summary."""
    model_name = request.form.get('model_name', '')
    display_name = request.form.get('model_display_name', '').strip()

    # Generate a display name if not provided
    if not display_name:
        display_name = model_name.split(':')[0].title() if model_name else request.form['api_type']

    config = ModelConfig(
        name=display_name,
        api_type=request.form['api_type'],
        endpoint_url=request.form['endpoint_url'],
        model_name=model_name,
        context_size=int(request.form['context_size']),
        dont_include_model='no_model_name' in request.form
    )

    # Update the endpoint file
    update_endpoint_file(endpoint_name, config)

    # Update session assignments
    assignments = session.get('assignments', {})
    assignments[endpoint_name] = asdict(config)
    session['assignments'] = assignments

    return redirect(url_for('complete'))


# ============================================================================
# Main
# ============================================================================

def main():
    """Entry point."""
    print("\n" + "="*60)
    print("  WilmerAI Web Setup Wizard")
    print("="*60)
    print(f"\n  Open your browser to: http://localhost:5099\n")
    print("  Press Ctrl+C to stop the server\n")
    print("="*60 + "\n")

    app.run(host='127.0.0.1', port=5099, debug=False)


if __name__ == '__main__':
    main()
