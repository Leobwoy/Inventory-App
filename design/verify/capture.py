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
         'settings': '/auth/settings', 'purchases': '/purchases/',
         'po': '/purchases/add'}

#: Pages that show one pane at a time. The sweep measures what is *visible*, so
#: without this the second pane of the sale form is never checked at all - and
#: it says nothing when it skips it. `sale` quietly dropped from 80 nodes to 78
#: when the page gained a second pane, which is not a number anyone would
#: notice. These get a second capture with the stepping script removed, so the
#: server-rendered `data-steps="off"` survives and both panes stay on screen.
PANED = {'sale'}

#: Pages carrying a dialog. Bootstrap's `.modal` is `display: none` until shown,
#: so a sweep of the ordinary capture measures none of it and reports clean
#: without having looked. These get a shot with the dialog forced open and the
#: page behind it removed, so what is measured is what a person actually sees.
DIALOGS = {'sale', 'po'}

#: Built from chr() rather than written out: an earlier version of this
#: pattern picked up a literal backspace byte from a stray escape, which
#: terminals and grep both render as nothing. The source read perfectly and
#: matched no scripts at all, and the sweep went on reporting the same node
#: count as before without a word.
SCRIPT_TAG = chr(60) + 'script[^>]*' + chr(62) + '.*?' + chr(60) + '/script' + chr(62)

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

                if name in DIALOGS:
                    # Forced open by class, not by script: the capture has no
                    # Bootstrap and no events, and `.show` plus an inline display
                    # is exactly the state Bootstrap leaves the element in.
                    shot = html.replace(
                        'class="modal fade picker-modal"',
                        'class="modal picker-modal show" style="display:block"')
                    if shot == html:
                        print(f'  {name}/{theme}: WARNING dialog capture changed '
                              'nothing - has the picker markup moved?')
                    # The list is filled by picker.js from the <select>, and
                    # nothing runs here, so it would be an empty box. Write the
                    # rows in from the same source the script uses.
                    options = re.findall(
                        r'<option value="(\d+)"[^>]*>([^<]+)</option>', shot)
                    rows = ''.join(
                        f'<li class="picker-option" role="option">'
                        f'<span class="picker-option-name">{label}</span>'
                        f'<span class="picker-option-meta">₵ 0.00</span></li>'
                        for _value, label in options[:12])
                    shot = re.sub(
                        r'(<ul class="picker-list"[^>]*>)\s*(</ul>)',
                        lambda m: m.group(1) + rows + m.group(2), shot)
                    (OUT / f'{name}dlg-{theme}.html').write_text(shot, encoding='utf-8')

                if name in PANED:
                    # Every script, not just the stepping one. The first attempt
                    # removed only the inline resolver and the sweep reported the
                    # exact same node count - the script at the foot of the page
                    # calls showStep() too and had put the pane straight back.
                    #
                    # No script at all is also the state a phone with a failed
                    # download is in, and `data-steps="off"` is what the server
                    # sends, so this measures a real state rather than a rigged
                    # one. The theme is already concrete in the server's HTML.
                    both = re.sub(SCRIPT_TAG, '', html, flags=re.S | re.I)
                    if 'data-steps="off"' not in both:
                        print(f'  {name}/{theme}: WARNING the both-panes capture '
                              'is not in the no-script state; it measures nothing new')
                    (OUT / f'{name}both-{theme}.html').write_text(both, encoding='utf-8')
    finally:
        owner.theme_pref = original
        db.session.commit()

# The sweep must be same-origin with the captures to read their iframes.
(ROOT / 'static' / '_sweep.html').write_text(
    SWEEP.read_text(encoding='utf-8'), encoding='utf-8')

files = sorted(p.name for p in OUT.iterdir())
print(f'captured {len(files)} pages, css busted with v={stamp}')
print(' ', ' '.join(files))
