"""Installable shell — Stage 2.4b.

Connectivity in this market is patchy and metered, so the app has to open from
a home screen icon and survive losing its signal without looking broken.

The rule these tests exist to protect: **pages are never written to the cache.**
Every page is behind a login and full of one business's money. Caching them
would leave those figures on the device after logout, readable on a shared
phone, and coming back hours stale as though they were current.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SW = (REPO_ROOT / 'static' / 'sw.js').read_text(encoding='utf-8')


def code_only(source):
    """Strip comments, so a test never matches a word that only appears in prose
    explaining why the code does not do that thing."""
    without_blocks = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return re.sub(r'//.*', '', without_blocks)


CODE = code_only(SW)
MANIFEST = json.loads((REPO_ROOT / 'static' / 'manifest.json').read_text(encoding='utf-8'))


# --- reachable at the right paths ------------------------------------------

def test_the_worker_is_served_from_the_site_root(client):
    """A worker can only control URLs under its own path. At /static/sw.js it
    would see nothing but /static - not one page of the app."""
    response = client.get('/sw.js')

    assert response.status_code == 200
    assert 'javascript' in response.headers['Content-Type']
    # Without this the browser keeps an old worker until the cache expires.
    assert 'no-cache' in response.headers.get('Cache-Control', '')


def test_the_worker_needs_no_login(client):
    """It is fetched by the browser, which sends no session for it."""
    assert client.get('/sw.js').status_code == 200
    assert client.get('/manifest.json').status_code == 200
    assert client.get('/offline').status_code == 200


def test_the_offline_page_does_not_redirect_to_a_login_that_cannot_load(client):
    """Served from the cache with no session. Bouncing to a login screen that
    also needs the network would answer one dead end with another."""
    response = client.get('/offline')

    assert response.status_code == 200
    assert b'No connection' in response.data


def test_the_offline_page_renders_the_same_whether_or_not_you_are_logged_in(register, client):
    """It first extended base.html, which branches on whether there is a session.
    The cached copy therefore rendered a full sidebar and no content at all for
    a logged-in reader - the one case that actually happens, since a user has a
    cookie long before they lose their signal."""
    logged_out = client.get('/offline').get_data(as_text=True)
    logged_in_client, _business_id = register()
    logged_in = logged_in_client.get('/offline').get_data(as_text=True)

    assert 'No connection' in logged_out
    assert 'No connection' in logged_in
    assert logged_out == logged_in

    # No navigation either: every link on it would be a page that cannot load.
    assert 'sidebar' not in logged_in
    assert 'Dashboard' not in logged_in


# --- the manifest ----------------------------------------------------------

def test_the_manifest_describes_an_installable_app():
    """Chrome refuses to offer installation unless all of these are present."""
    assert MANIFEST['name']
    assert MANIFEST['start_url'] == '/'
    assert MANIFEST['display'] == 'standalone'
    assert MANIFEST['theme_color'].startswith('#')

    sizes = {icon['sizes'] for icon in MANIFEST['icons']}
    assert '192x192' in sizes and '512x512' in sizes


def test_a_maskable_icon_is_offered():
    """Android crops icons to the launcher's shape. Without a maskable variant
    the mark gets clipped, or sits in a white box on a dark home screen."""
    purposes = {icon.get('purpose') for icon in MANIFEST['icons']}
    assert 'maskable' in purposes


@pytest.mark.parametrize('icon', MANIFEST['icons'])
def test_every_declared_icon_exists(icon, client):
    """A 404 here is a silent refusal to install, with no error anywhere."""
    response = client.get(icon['src'])
    assert response.status_code == 200, f"{icon['src']} is declared but missing"
    assert len(response.data) > 0


def test_the_page_head_links_the_manifest_and_registers_the_worker(register):
    client, _business_id = register()
    body = client.get('/').get_data(as_text=True)

    assert 'rel="manifest"' in body
    assert 'theme-color' in body
    assert "navigator.serviceWorker.register('/sw.js')" in body
    assert 'apple-touch-icon' in body


# --- what the worker will and will not keep --------------------------------

def test_the_worker_never_caches_a_page():
    """The whole point. cache.put must not be reachable from the navigation
    path, or a business's balances end up on disk."""
    # Isolate the page handler and prove it only ever reads from the cache.
    handler = CODE.split('async function networkOnlyWithOfflinePage')[1]
    assert 'caches.match' in handler
    assert 'cache.put' not in handler
    assert 'cache.add' not in handler


def test_only_static_assets_are_written_to_the_cache():
    """cacheFirst is the one place that writes, and it is reached only for
    /static/ URLs."""
    assert CODE.count('cache.put') == 1
    writer = CODE.split('async function cacheFirst')[1].split('async function')[0]
    assert 'cache.put' in writer

    dispatch = CODE.split("addEventListener('fetch'")[1].split('async function')[0]
    assert 'isStaticAsset(url)' in dispatch
    assert 'cacheFirst(request)' in dispatch


def test_the_worker_ignores_anything_that_is_not_a_get():
    """Replaying a POST out of a cache would record a sale twice."""
    dispatch = CODE.split("addEventListener('fetch'")[1].split('async function')[0]
    assert re.search(r"request\.method\s*!==\s*'GET'", dispatch)


def test_the_worker_ignores_other_origins():
    dispatch = CODE.split("addEventListener('fetch'")[1].split('async function')[0]
    assert 'url.origin !== self.location.origin' in dispatch


def test_old_caches_are_cleared_on_activate():
    """Otherwise every deploy leaves another copy of the assets on a phone that
    has little room to spare."""
    activate = CODE.split("addEventListener('activate'")[1].split('function isStaticAsset')[0]
    assert 'caches.delete' in activate
    assert 'CACHE_VERSION' in activate


def test_precached_files_all_exist():
    """A precache list is written by hand and rots silently: the worker still
    installs, and the missing file only shows up offline."""
    listed = re.search(r'const PRECACHE = \[(.*?)\];', CODE, re.S).group(1)
    paths = re.findall(r"'(/[^']+)'", listed)
    assert paths, 'no precache entries found'

    for path in paths:
        if path == '/offline':
            continue                     # a route, not a file
        assert (REPO_ROOT / path.lstrip('/')).is_file(), f'{path} is precached but missing'


def test_precaching_survives_one_missing_file():
    """addAll rejects the whole install if any single entry 404s, leaving the
    user with no worker at all over one renamed asset."""
    install = CODE.split("addEventListener('install'")[1].split("addEventListener('activate'")[0]
    assert 'addAll' not in install
    assert '.catch(' in install


# --- production configuration ----------------------------------------------

def test_the_app_refuses_to_start_in_production_without_a_secret_key(monkeypatch):
    """A published default key is not a weak key, it is no key: anyone who has
    read this repository could forge a session cookie and sign in as any user of
    any business. Better to fail the deploy than to serve that."""
    import app as app_module

    monkeypatch.setenv('TRACKTRACK_ENV', 'production')
    monkeypatch.delenv('SECRET_KEY', raising=False)

    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        app_module.create_app()


def test_production_marks_the_session_cookie_secure(monkeypatch):
    """Koyeb terminates TLS and forwards plain http, so without ProxyFix Flask
    thinks every request is insecure and declines to set the Secure cookie."""
    import app as app_module

    monkeypatch.setenv('TRACKTRACK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'x' * 64)
    built = app_module.create_app()

    assert built.config['SESSION_COOKIE_SECURE'] is True
    assert built.config['SESSION_COOKIE_HTTPONLY'] is True
    assert built.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    assert 'ProxyFix' in type(built.wsgi_app).__name__


def test_development_still_starts_without_a_secret_key(monkeypatch):
    """The guard must not make the app unrunnable on a laptop."""
    import app as app_module

    monkeypatch.delenv('TRACKTRACK_ENV', raising=False)
    monkeypatch.delenv('SECRET_KEY', raising=False)

    built = app_module.create_app()
    assert built.config['SECRET_KEY']
    assert built.config['SESSION_COOKIE_SECURE'] is not True


def test_the_hidden_attribute_actually_hides():
    """Browsers implement `hidden` as `[hidden] { display: none }`, and every
    Bootstrap display utility is `!important` - so `class="d-flex" hidden`
    renders in full. That is how the sale form's "No connection" banner showed
    on a working connection, and the discount summary showed a discount of
    zero, each stating something untrue."""
    # code_only, or this matches the example inside the comment that explains
    # the rule rather than the rule itself.
    css = code_only((REPO_ROOT / 'static' / 'css' / 'style.css').read_text(encoding='utf-8'))
    rule = re.search(r'\[hidden\]\s*\{([^}]*)\}', css)

    assert rule, 'no [hidden] rule in style.css'
    # The whole declaration, not three tokens that happen to be present:
    # `display: block !important; content: none` satisfies a token check
    # while leaving every [hidden] element on screen.
    declaration = re.sub(r'\s+', '', rule.group(1))
    assert 'display:none!important' in declaration, (
        "the [hidden] rule must set display: none !important, or Bootstrap's "
        "display utilities still win")


# --- the stale-cache guard ----------------------------------------------------

#: Fingerprint of everything in PRECACHE, per CACHE_VERSION.
#:
#: The precached files are served **cache-first**, so changing one without
#: bumping CACHE_VERSION leaves every existing user on the old copy for good —
#: reloading does not help, because the worker never asks the network. That has
#: already shipped once: the collapsible sidebar went out with unstyled buttons
#: because style.css changed and the version did not, and it read as a CSS bug
#: rather than a stale file.
#:
#: So the fingerprint is recorded here. Change an asset and this test fails,
#: naming the fix: bump the version, then update the hash below.
PRECACHE_FINGERPRINT = {
    'tracktrack-v15': '5b700293298fb69b98d8fe120b0c30b229c2eceba62eac7ba28448db0a58fdc6',
    'tracktrack-v16': '16e8f134c83169202b3b495fc829c687a105eb80f38b431d67e89bd5fa1e6f61',
}


def precache_paths():
    listed = re.search(r'const PRECACHE = \[(.*?)\];', SW, re.S).group(1)
    return [p for p in re.findall(r"'([^']+)'", listed) if p.startswith('/static/')]


def precache_fingerprint():
    """One hash over every precached file, stable across checkouts.

    Text is normalised to LF first: this repository is worked on from Windows,
    and a CRLF checkout would otherwise fingerprint differently from CI for
    files nobody has touched.
    """
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(precache_paths()):
        target = REPO_ROOT / path.lstrip('/')
        if not target.exists():
            continue                # covered separately by the missing-file test
        raw = target.read_bytes()
        try:
            raw = raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
        except UnicodeDecodeError:
            pass                    # a png or a woff2; hash the bytes as they are
        digest.update(path.encode('utf-8'))
        digest.update(raw)
    return digest.hexdigest()


def test_every_precached_file_exists():
    """A 404 in the precache list makes `addAll` reject, and then *nothing* is
    cached — one wrong path silently disables the whole offline shell."""
    missing = [p for p in precache_paths()
               if not (REPO_ROOT / p.lstrip('/')).exists()]
    assert not missing, f'PRECACHE lists files that do not exist: {missing}'


def test_changing_a_precached_asset_requires_bumping_the_cache_version():
    version = re.search(r"const CACHE_VERSION = '([^']+)'", SW).group(1)
    actual = precache_fingerprint()
    recorded = PRECACHE_FINGERPRINT.get(version, 'MISSING')

    if recorded is None or recorded == 'MISSING':
        pytest.fail(
            f'No fingerprint recorded for CACHE_VERSION {version!r}.\n'
            f'If you have just bumped the version, record it:\n\n'
            f"    '{version}': '{actual}',\n")

    assert recorded == actual, (
        f'A file in PRECACHE changed but CACHE_VERSION is still {version!r}.\n'
        f'Those files are served cache-first, so every existing user would keep\n'
        f'the old copy indefinitely. Bump CACHE_VERSION in static/sw.js, then\n'
        f'record the new fingerprint here:\n\n'
        f"    '<new-version>': '{actual}',\n")
