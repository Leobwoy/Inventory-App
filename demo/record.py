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

#: The line the sale scene rings up. Change it to something your audience
#: recognises - the whole point of that scene is a product they know, sold in
#: the unit they sell it in. It must be active, in stock, and have a real pack.
SELL = {'search': 'Vitamalt', 'name': 'Vitamalt 330ml', 'cartons': '2'}


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

    def __init__(self, page, speed=1.0, context=None):
        self.page = page
        self.context = context
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
        # Typed character by character, because a field being filled is the part
        # that reads as somebody using the app rather than a page changing.
        target.fill('')
        target.type(str(text), delay=110 * self.speed)
        self.beat(settle)

        # Then check, *after* settling rather than before. The quantity box
        # normalises itself a moment after the last keystroke - an empty field
        # becomes 1 - so a check run immediately saw the right value and the
        # recording showed the wrong one. This is the difference between a demo
        # that says two cartons and one that quietly says one.
        if (target.input_value() or '').strip() != str(text):
            target.fill(str(text))
            target.dispatch_event('input')
            target.dispatch_event('change')
            self.beat(0.6)
        return True

    def set_quantity(self, value, settle=1.4):
        """Reach the quantity with the page's own + button.

        Typing into the box was tried three ways and lost the value every time:
        the form read back what had been typed, the running summary agreed, and
        the invoice still recorded one carton. The stepper beside the field
        keeps its own count, so writing the input behind its back leaves the two
        disagreeing and the stepper wins at submit.

        Pressing + is also simply what a person does, so the demo shows the
        control a wholesaler will actually use rather than a scripted paste.
        """
        target = self.point_at('[name$="quantity"]')
        if target is None:
            print('  ! no quantity box')
            return False

        wanted = int(value)
        for _ in range(wanted * 3):          # a ceiling, so a stuck page ends
            current = (target.input_value() or '').strip()
            if current == str(wanted):
                break
            if not self.tap('.qty-step[data-step="1"]', settle=0.55):
                break

        told = self.page.locator('#summary-count')
        summary = told.inner_text().strip() if told.count() else ''
        got = (target.input_value() or '').strip()
        self.beat(settle)
        if got != str(wanted):
            print('  ! quantity stuck at %r, wanted %s' % (got, wanted))
            return False
        print('    quantity %s -> %s' % (got, summary))
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
    take.say('Every morning, TrackTrack opens on what needs you.', hold=3.4)
    take.scroll(400)
    take.say('Not a menu. A list that empties itself.', hold=3.4)


def scene_sell(take):
    """The shot that wins the room, so it runs longest and finishes the job.

    The first version stopped at a half-filled form. A wholesaler watching
    needs to see the sale *land* - the quantity in cartons, the total, and an
    invoice that says two cartons rather than forty-eight bottles. Anything
    short of that is a screenshot with a cursor on it.
    """
    take.go('/sales/add')
    take.say('Say you are selling two cartons of %s.' % SELL['name'], hold=3.2)

    take.tap('.picker-button', settle=1.4)
    # Searched by name rather than picked off the list, because a wholesaler
    # with four hundred lines will search, and because it puts the product we
    # are talking about on screen instead of whatever sorts first.
    take.type_into('.picker-search', SELL['search'], settle=1.2)
    take.say('Find it by name.', hold=2.2)
    if not take.tap('.picker-option:not([hidden])', settle=1.4):
        take.page.keyboard.press('Escape')
        take.dress()

    take.set_quantity(SELL['cartons'], settle=1.6)
    take.say('Two. Not forty-eight.', hold=3.0)
    take.scroll(220, steps=5)
    take.say('It is already counting in cartons, because that is how you sell.',
             hold=3.6)

    take.tap('.sale-next', settle=1.6)
    take.say('Who bought it, and how they paid.', hold=3.0)
    take.tap('.chip-set label.chip', index=2, settle=1.4)
    take.say('This one goes on credit.', hold=2.8)

    take.tap('.sale-submit', settle=2.2)
    take.say('And the invoice says two cartons.', hold=3.8)
    take.scroll(300, steps=6)
    take.say('Forty-eight bottles left the shelf on their own.', hold=3.6)


def scene_owed(take):
    take.go('/credit/')
    take.say('The money still out there, oldest debt first.', hold=3.4)
    take.scroll(420)
    take.say('By name, by how old it is, and what they paid last.', hold=3.6)


def scene_restock(take):
    take.go('/purchases/add')
    take.say('When you restock, it remembers what you paid before.', hold=3.4)
    take.tap('.picker-button', settle=1.4)
    if not take.tap('.picker-option:not([hidden])', settle=1.4):
        take.page.keyboard.press('Escape')
        take.dress()
    take.scroll(240, steps=5)
    take.say('And who you paid it to, so you can see who is cheapest.', hold=3.8)


def scene_receive(take):
    take.go('/purchases/')
    take.say('Goods arrive. You receive them line by line.', hold=3.4)
    take.scroll(320)
    take.say('Part of an order today, the rest next week. Stock only moves here.',
             hold=3.8)


def scene_stock(take):
    take.go('/products/')
    take.say('Stock counted the way you buy it.', hold=3.0)
    take.scroll(380)
    take.say('Cartons, and the loose bottles that are really on the floor.',
             hold=3.6)


def scene_offline(take):
    """Recorded with the network genuinely cut, not mimed.

    Chromium can be told to go offline at the browser level, which is the real
    thing rather than a screenshot of a banner - the page fails the same way it
    fails in a doorway with no signal.
    """
    take.go('/sales/add')
    # Wait for the service worker to actually be in charge. A fresh browser
    # has no cache, so cutting the network a moment too early gets the
    # browser's own error page - which films as the app failing rather than
    # surviving, which is the opposite of the point.
    if not take.page.evaluate('() => navigator.serviceWorker ? navigator.serviceWorker.ready.then(() => true).catch(() => false) : false'):
        print('  ! no service worker - skipping the offline scene')
        return
    take.beat(1.5)

    take.say('And when the network goes.', hold=2.6)
    take.context.set_offline(True)
    take.beat(1.2)
    take.page.reload(wait_until='domcontentloaded')
    take.dress()
    take.beat(1.4)
    take.say('You keep selling. It queues, and syncs when the signal comes back.',
             hold=4.0)
    take.context.set_offline(False)
    take.beat(1.2)


def scene_reports(take):
    take.go('/reports/sales')
    take.say('What sold, what it cost you, what is on the shelf.', hold=3.4)
    take.scroll(360)
    take.say('Every report says which unit its numbers are in.', hold=3.4)


def scene_plans(take):
    take.go('/billing/')
    take.say('It starts free. Twenty products, one person.', hold=3.4)
    take.scroll(420)
    take.say('Grow, and the plan grows with you. Nothing renews on its own.',
             hold=4.0)


def scene_close(take):
    take.go('/')
    take.say('TrackTrack. Know your stock, know who owes you.', hold=4.5)
    take.hush()
    take.beat(1.2)


#: The long cut, for a sit-down pitch. Order matters - it is a day.
SCENES = [
    ('what needs you', scene_attention),
    ('the sale',       scene_sell),
    ('who owes you',   scene_owed),
    ('restocking',     scene_restock),
    ('goods in',       scene_receive),
    ('the shelf',      scene_stock),
    ('no network',     scene_offline),
    ('reports',        scene_reports),
    ('what it costs',  scene_plans),
    ('the card',       scene_close),
]

#: The short cut, for forwarding. Four beats and out.
SHORT = ['the sale', 'who owes you', 'no network', 'the card']


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
    parser.add_argument('--speed', type=float, default=1.25,
                        help='multiplies every pause; 1.0 is brisk, 1.5 slower')
    parser.add_argument('--cut', choices=['full', 'short'], default='full',
                        help='full for a sit-down pitch, short for forwarding')
    parser.add_argument('--only', help='record one scene by name')
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob('*.webm'):
        stale.unlink()

    scenes = SCENES
    if args.cut == 'short':
        scenes = [s for s in SCENES if s[0] in SHORT]
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

        take = Take(page, speed=args.speed, context=context)
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

    name = 'tracktrack-demo%s.mp4' % ('-short' if args.cut == 'short' else '')
    final = to_mp4(raw, OUT / name)
    size = final.stat().st_size / 1_000_000
    print('\nDone: %s (%.1f MB)' % (final, size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
