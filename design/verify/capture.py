"""Capture each page in each theme, with a cache-busted stylesheet.

Rendering server-side per theme rather than flipping the attribute in the
browser: the attribute is only half of it, and a page rendered for one theme and
mutated into the other was giving nonsense numbers.
"""
import pathlib
import re
import sys
import time
import urllib.request

# Derived from this file, not hardcoded: the repository is not always checked
# out to the machine this was first written on.
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import app as appmod
from flask.sessions import SecureCookieSessionInterface

PORT = sys.argv[1] if len(sys.argv) > 1 else '5000'
BASE = f'http://localhost:{PORT}'
OUT = ROOT / 'static' / '_shot'
SWEEP = ROOT / 'design' / 'verify' / 'sweep.html'

PAGES = {'dashboard': '/', 'products': '/products/', 'sale': '/sales/add',
         'credit': '/credit/', 'alerts': '/products/alerts',
         'settings': '/auth/settings', 'purchases': '/purchases/'}

a = appmod.create_app()
stamp = int(time.time())

if OUT.exists():
    for f in OUT.iterdir():
        f.unlink()
OUT.mkdir(parents=True, exist_ok=True)

with a.app_context():
    from extensions import db
    from auth.models import User
    owner = User.query.order_by(User.id).first()
    cookie = SecureCookieSessionInterface().get_signing_serializer(a).dumps(
        {'_user_id': str(owner.id), '_fresh': True})

    # Whatever it was before, not 'system': this runs against a development
    # database a person also uses, and a crash halfway through would otherwise
    # leave them staring at a theme they never chose.
    original = owner.theme_pref
    try:
        for theme in ('light', 'dark'):
            owner.theme_pref = theme
            db.session.commit()
            for name, path in PAGES.items():
                req = urllib.request.Request(
                    BASE + path, headers={'Cookie': f'session={cookie}'})
                try:
                    html = urllib.request.urlopen(req).read().decode('utf-8')
                except Exception as e:
                    print(f'  {name}/{theme}: FAILED {e}')
                    continue
                # Bust every stylesheet, or the browser serves the copy from
                # before the last edit and every measurement describes the past.
                html = re.sub(r'(href="/static/css/[^"]+?)(")',
                              rf'\1?v={stamp}\2', html)
                (OUT / f'{name}-{theme}.html').write_text(html, encoding='utf-8')
    finally:
        owner.theme_pref = original
        db.session.commit()

# The sweep must be same-origin with the captures to read their iframes.
(ROOT / 'static' / '_sweep.html').write_text(
    SWEEP.read_text(encoding='utf-8'), encoding='utf-8')

files = sorted(p.name for p in OUT.iterdir())
print(f'captured {len(files)} pages, css busted with v={stamp}')
print(' ', ' '.join(files))
