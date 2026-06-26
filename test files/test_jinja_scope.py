from flask import Flask, render_template_string

app = Flask(__name__)

template = """
{% set grand_total = 0 %}
{% for i in range(3) %}
    {% set grand_total = grand_total + 10 %}
    Inside loop: {{ grand_total }}
{% endfor %}
Outside loop: {{ grand_total }}
"""

with app.app_context():
    print("Testing Jinja2 scoping...")
    rendered = render_template_string(template)
    print(rendered)
