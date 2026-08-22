# -*- coding: utf-8 -*-
"""Record a walkthrough of the real application as a phone-shaped video.

Run it, get an MP4. See demo/README.md for why this is a script rather than a
screen recording.

The three things that make it look like a demo rather than a slideshow, all of
which a plain capture gives you for free and an automated one does not:

* **A cursor.** Chromium does not record a pointer, so pages appear to change by
  themselves. This draws one and glides it between targets.
* **Captions.** Drawn into the page while recording, so the finished file needs
  no editing and there is nothing to sync.
* **Pauses.** A script clicks faster than anybody can read. Every wait here is
  deliberate and tuned for somebody seeing the app for the first time.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / 'out'

# A tall phone, and the video canvas must match the viewport exactly.
#
# Setting it larger does not render bigger - Playwright captures at CSS
# resolution and pads the page into the corner of the oversized frame, which is
# what the first take of this did: a phone-sized picture adrift in grey. Real
# detail is capped by the viewport, so the viewport is as large as the phone
# layout allows (the app switches to desktop above 768px) and ffmpeg scales the
# finished file up to something a modern handset fills its screen with.
VIEWPORT = {'width': 500, 'height': 1080}
VIDEO = dict(VIEWPORT)
SCALE = 2
UPSCALE = 'scale=1000:2160:flags=lanczos'


# --- the furniture the page does not come with -------------------------------

CHROME = """
(() => {
  if (document.getElementById('demo-chrome')) { return; }
  const style = document.createElement('style');
  style.id = 'demo-chrome';
  style.textContent = `
    #demo-cursor {
      position: fixed; z-index: 2147483647; width: 22px; height: 22px;
      margin: -11px 0 0 -11px; border-radius: 50%;
      background: rgba(37,99,235,.35); border: 2px solid #2563eb;
      box-shadow: 0 2px 10px rgba(0,0,0,.35); pointer-events: none;
      transition: transform .45s cubic-bezier(.4,0,.2,1); left: 0; top: 0;
    }
    #demo-cursor.tap { animation: demo-tap .35s ease-out; }
    @keyframes demo-tap {
      0% { box-shadow: 0 0 0 0 rgba(37,99,235,.5); }
      100% { box-shadow: 0 0 0 22px rgba(37,99,235,0); }
    }
    #demo-caption {
      position: fixed; left: 16px; right: 16px; bottom: 28px; z-index: 2147483646;
      background: rgba(9,13,20,.90); color: #fff; border-radius: 14px;
      padding: 14px 18px; font: 600 17px/1.4 system-ui, -apple-system, sans-serif;
      text-align: center; pointer-events: none; opacity: 0;
      transition: opacity .3s ease; backdrop-filter: blur(6px);
    }
    #demo-caption.on { opacity: 1; }
  `;
  document.head.appendChild(style);
  const dot = document.createElement('div'); dot.id = 'demo-cursor';
  const cap = document.createElement('div'); cap.id = 'demo-caption';
  document.body.appendChild(dot); document.body.appendChild(cap);
  window.__demo = {
    move(x, y) { dot.style.transform = `translate(${x}px, ${y}px)`; },
    tap() { dot.classList.remove('tap'); void dot.offsetWidth; dot.classList.add('tap'); },
    say(text) { cap.textContent = text; cap.classList.add('on'); },
    hush() { cap.classList.remove('on'); }
  };
})();
"""


class Take:
    """One recording pass. Wraps a page with a cursor, captions and pacing."""

    def __init__(self, page, speed=1.0):
        self.page = page
        self.speed = speed

    def beat(self, seconds=1.0):
        time.sleep(seconds * self.speed)

    def dress(self):
        """Put the cursor and caption back. Needed after every navigation."""
        self.page.evaluate(CHROME)

    def say(self, text, hold=None):
        # Re-dress first. A navigation wipes the caption, and the guard inside
        # CHROME makes dress() a no-op when it is already there - so this is
        # cheap when nothing is wrong and the difference between a caption and
        # silence when something is.
        if not self.page.evaluate('() => !!window.__demo'):
            self.dress()
        self.page.evaluate('t => window.__demo && window.__demo.say(t)', text)
        if hold:
            self.beat(hold)

    def hush(self):
        self.page.evaluate('() => window.__demo && window.__demo.hush()')

    def point_at(self, selector, index=0):
        """Glide the cursor onto an element and return it, or None."""
        found = self.page.locator(selector)
        if found.count() <= index:
            return None
        target = found.nth(index)
        try:
            target.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            return None
        box = target.bounding_box()
        if not box:
            return None
        self.page.evaluate('p => window.__demo && window.__demo.move(p.x, p.y)',
                           {'x': box['x'] + box['width'] / 2,
                            'y': box['y'] + box['height'] / 2})
        self.beat(0.5)
        return target

    def tap(self, selector, index=0, settle=1.2):
        """Point, press, wait. Returns False when the target is not on the page,
        so a scene can skip rather than the whole take dying."""
        target = self.point_at(selector, index)
        if target is None:
            print('  ! not on this page: %s' % selector)
            return False
        self.page.evaluate('() => window.__demo && window.__demo.tap()')
        self.beat(0.25)
        try:
            target.click(timeout=5000)
        except Exception as error:
            print('  ! could not press %s (%s)' % (selector, type(error).__name__))
            return False
        self.page.wait_for_load_state('networkidle', timeout=15000)
        self.dress()
        self.beat(settle)
        return True

    def type_into(self, selector, text, settle=0.8):
        target = self.point_at(selector)
        if target is None:
            print('  ! no field: %s' % selector)
            return False
        self.page.evaluate('() => window.__demo && window.__demo.tap()')
        target.click()
        target.fill('')
        target.type(str(text), delay=110 * self.speed)
        # Typed values do not always survive a field that re-renders on input,
        # and an empty quantity box is the one thing this demo cannot show.
        if (target.input_value() or '').strip() != str(text):
            target.fill(str(text))
            target.dispatch_event('input')
            target.dispatch_event('change')
        self.beat(settle)
        return True

    def scroll(self, pixels=340, steps=7):
        """Slow enough to read. One jump reads as a cut, not a scroll."""
        for _ in range(steps):
            self.page.mouse.wheel(0, pixels / steps)
            self.beat(0.09)
        self.beat(0.5)

    def go(self, path, settle=1.4):
        self.page.goto(self.base + path, wait_until='networkidle')
        self.dress()
        self.beat(settle)


# --- the film ----------------------------------------------------------------
#
# Each scene is a caption and a short routine. Reorder them, retime them,
# rewrite the words - it is a list, not a program. Keep every caption under
# about twelve words: it is read on a phone, once, while something moves.

def scene_attention(take):
    take.go('/')
    take.say('Every morning, TrackTrack opens on what needs you.', hold=2.6)
    take.scroll(400)
    take.say('Not a menu. A list that empties itself.', hold=2.8)


def scene_sell(take):
    take.go('/sales/add')
    take.say('You sell by the carton, so it counts by the carton.', hold=2.4)
    take.tap('.picker-button', settle=1.4)
    take.say('Pick the product.', hold=1.4)
    if not take.tap('.picker-option', settle=1.2):
        take.page.keyboard.press('Escape')
        take.dress()
    take.type_into('[name$="quantity"]', '2', settle=1.0)
    take.say('Two cartons.', hold=2.0)
    take.scroll(260, steps=5)
    take.say('The shelf drops by forty-eight bottles on its own.', hold=3.0)


def scene_owed(take):
    take.go('/credit/')
    take.say('And the money still out there.', hold=2.4)
    take.scroll(420)
    take.say('By name, by how old it is, and what they paid last.', hold=3.0)


def scene_restock(take):
    take.go('/purchases/add')
    take.say('When you restock, it remembers what you paid before.', hold=2.6)
    take.scroll(300, steps=6)
    take.say('And who you paid it to.', hold=2.4)


def scene_stock(take):
    take.go('/products/')
    take.say('Stock counted the way you buy it. Cartons, and the loose bottles.',
             hold=3.2)
    take.scroll(380)
    take.beat(1.2)


def scene_close(take):
    take.go('/')
    take.say('TrackTrack. Know your stock, know who owes you.', hold=4.0)
    take.hush()
    take.beat(1.0)


SCENES = [
    ('what needs you', scene_attention),
    ('the sale',       scene_sell),
    ('who owes you',   scene_owed),
    ('restocking',     scene_restock),
    ('the shelf',      scene_stock),
    ('the card',       scene_close),
]


# --- running it --------------------------------------------------------------

def sign_in(take, email, password):
    take.go('/auth/login', settle=1.0)
    take.say('', hold=0)
    take.hush()
    take.page.fill('#email', email)
    take.page.fill('#password', password)
    take.page.click('button[type="submit"]')
    take.page.wait_for_load_state('networkidle', timeout=20000)
    take.dress()
    if '/auth/login' in take.page.url:
        raise SystemExit(
            'Sign-in failed - check --email and --password against that site.')


def _find_ffmpeg():
    """ffmpeg, wherever it landed.

    `shutil.which` alone is not enough on Windows: winget drops a shim in
    the WinGet Links folder and adds that to the user PATH, but a shell
    opened *before* the install keeps the old PATH and never sees it. That
    is a confusing way to fail - the tool is installed and the script says
    it is not - so look in the usual places before giving up.
    """
    import os

    found = shutil.which('ffmpeg')
    if found:
        return found
    candidates = [
        pathlib.Path(os.environ.get('LOCALAPPDATA', ''))
        / 'Microsoft' / 'WinGet' / 'Links' / 'ffmpeg.exe',
        pathlib.Path('C:/ProgramData/chocolatey/bin/ffmpeg.exe'),
        pathlib.Path('/usr/bin/ffmpeg'),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def to_mp4(webm, mp4):
    """H.264 in yuv420p with the index at the front.

    Not tidiness: WebM does not play on an iPhone, and a video a pilot client
    cannot open is worse than no video. yuv420p is the pixel format every phone
    decoder actually supports, and -movflags +faststart lets it start before it
    has finished downloading, which is how it will be watched.
    """
    exe = _find_ffmpeg()
    if not exe:
        print('')
        print('ffmpeg not found - leaving the WebM at %s' % webm)
        print('  Install it with:  winget install Gyan.FFmpeg')
        return webm
    subprocess.run(
        [exe, '-y', '-i', str(webm),
         '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
         '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
         '-vf', UPSCALE,
         str(mp4)],
        check=True, capture_output=True)
    return mp4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:5000',
                        help='the site to record')
    parser.add_argument('--email', default='owner@accrabev.com')
    parser.add_argument('--password', default='TrackTrack!23')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='multiplies every pause; 0.7 is brisker, 1.3 slower')
    parser.add_argument('--only', help='record one scene by name')
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob('*.webm'):
        stale.unlink()

    scenes = SCENES
    if args.only:
        scenes = [s for s in SCENES if s[0] == args.only]
        if not scenes:
            raise SystemExit('No scene called %r. Try: %s'
                             % (args.only, ', '.join(n for n, _ in SCENES)))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT, device_scale_factor=SCALE,
            record_video_dir=str(OUT), record_video_size=VIDEO,
            # Phone layout is what the app serves under 768px, and it is the
            # layout this market actually uses.
            is_mobile=True, has_touch=True,
            user_agent=('Mozilla/5.0 (Linux; Android 13; Pixel 7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0 Mobile Safari/537.36'),
            color_scheme='light')
        page = context.new_page()

        take = Take(page, speed=args.speed)
        take.base = args.url.rstrip('/')

        print('Recording %s' % take.base)
        sign_in(take, args.email, args.password)
        for name, scene in scenes:
            print('  scene: %s' % name)
            scene(take)

        video = page.video
        context.close()
        browser.close()
        raw = pathlib.Path(video.path())

    final = to_mp4(raw, OUT / 'tracktrack-demo.mp4')
    size = final.stat().st_size / 1_000_000
    print('\nDone: %s (%.1f MB)' % (final, size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
