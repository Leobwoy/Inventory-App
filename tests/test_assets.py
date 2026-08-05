"""Assets must be served from this app, not from a CDN.

A service worker cannot reliably cache cross-origin responses, so a single CDN
link is enough to make the app fail offline - which is the whole point of Stage
2.4. It is also metered mobile data on every visit. These tests fail the moment
someone reintroduces one.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / 'templates'
STATIC = REPO_ROOT / 'static'

# src="https://..." or href="https://..." - a fetched subresource, not a link
# the user clicks.
EXTERNAL_ASSET = re.compile(r'(?:src|href)\s*=\s*["\']https?://', re.IGNORECASE)

VENDORED = [
    'vendor/bootstrap/bootstrap.min.css',
    'vendor/bootstrap/bootstrap.bundle.min.js',
    'vendor/bootstrap-icons/bootstrap-icons.min.css',
    'vendor/bootstrap-icons/fonts/bootstrap-icons.woff2',
    'vendor/bootstrap-icons/fonts/bootstrap-icons.woff',
    'vendor/chart/chart.umd.min.js',
    'js/combobox.js',
    'css/combobox.css',
]


def test_no_template_loads_an_asset_from_another_origin():
    """One CDN link makes the app unusable offline and costs data every visit."""
    offenders = []
    for template in TEMPLATES.rglob('*.html'):
        for number, line in enumerate(template.read_text(encoding='utf-8').splitlines(), 1):
            if EXTERNAL_ASSET.search(line):
                offenders.append(f'{template.relative_to(REPO_ROOT)}:{number} {line.strip()}')
    assert offenders == [], 'Serve these from static/ instead:\n' + '\n'.join(offenders)


@pytest.mark.parametrize('relative_path', VENDORED)
def test_vendored_asset_is_present(relative_path):
    """A missing vendored file is an unstyled app, and only shows up in a browser."""
    asset = STATIC / relative_path
    assert asset.is_file(), f'static/{relative_path} is missing'
    assert asset.stat().st_size > 0, f'static/{relative_path} is empty'


def test_bootstrap_icons_css_points_at_the_fonts_we_vendored():
    """The icon font is a second hop; if the relative path is wrong every icon
    silently renders as an empty box."""
    css = (STATIC / 'vendor/bootstrap-icons/bootstrap-icons.min.css').read_text(encoding='utf-8')
    referenced = set(re.findall(r'url\(["\']([^"\'?)]+)', css))
    assert referenced, 'no font url() found - wrong file downloaded?'
    for href in referenced:
        assert (STATIC / 'vendor/bootstrap-icons' / href).is_file(), f'{href} not vendored'


def test_sale_form_uses_the_local_combobox(register, make_product):
    """The sale form was the only page needing jQuery and Select2 - 150KB for one
    dropdown. If they come back, they come back as a network dependency."""
    client, business_id = register()
    make_product(business_id, name='Club Beer 625ml')

    response = client.get('/sales/add')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '/static/js/combobox.js' in body
    assert 'data-combobox' in body
    assert 'select2' not in body.lower()
    assert 'jquery' not in body.lower()
