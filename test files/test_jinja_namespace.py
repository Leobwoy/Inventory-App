from flask import Flask, render_template_string

app = Flask(__name__)

template = """
{% set ns = namespace(total=0) %}
{% for i in range(3) %}
    {% set ns.total = ns.total + 10 %}
{% endfor %}
Outside loop: {{ ns.total }}
"""

with app.app_context():
    try:
        print("Testing Jinja2 namespace...")
        rendered = render_template_string(template)
        print(rendered)
    except Exception as e:
        print(f"Error: {e}")
