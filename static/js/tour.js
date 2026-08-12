/* A guided tour of the app, for someone who has just registered.
 *
 * Hand-written rather than a library, for the same reason nothing else here
 * loads from a CDN (2.4a): the service worker cannot reliably cache a
 * cross-origin response, and this has to work on the market-day connection the
 * whole product is designed around.
 *
 * Three rules shape it:
 *
 * 1. **A step whose anchor is not on the page is dropped, not shown empty.**
 *    The sidebar is permission-gated, so a Sales Staff member simply has no
 *    Suppliers link - and walking them through a feature they cannot open is
 *    worse than saying nothing. This falls out of anchoring to the real
 *    elements instead of keeping a second list of who sees what.
 * 2. **Nothing is trapped.** Skip moves past a step; the close button ends the
 *    tour for good. Escape does the same. A tour you cannot leave is a modal
 *    that has taken the app hostage.
 * 3. **It is told once.** Completion is recorded against the user on the
 *    server, not in localStorage, so it does not start again on their second
 *    device or after a browser clean-up.
 */
(function () {
  'use strict';

  var DESKTOP_MIN = 992;          // matches the CSS breakpoint for the drawer
  var GAP = 12;                   // space between the highlight and the bubble

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text) { node.textContent = text; }     // textContent, never innerHTML
    return node;
  }

  function Tour(steps, options) {
    this.all = steps || [];
    this.options = options || {};
    this.index = 0;
    this.nodes = null;
    this.onResize = this.reposition.bind(this);
  }

  /* Only the steps whose anchor actually exists for this person. */
  Tour.prototype.applicable = function () {
    return this.all.filter(function (step) {
      return document.querySelector(step.anchor) !== null;
    });
  };

  Tour.prototype.start = function () {
    this.steps = this.applicable();
    if (!this.steps.length) { return; }
    this.index = 0;
    this.build();
    this.show();
  };

  Tour.prototype.build = function () {
    var self = this;

    // Where focus was before we took it, so it can be handed back on close.
    // Without this a keyboard user is dropped at the top of the document after
    // dismissing the tour, having lost their place entirely.
    this.previousFocus = document.activeElement;

    var root = el('div', 'tour-root');
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-labelledby', 'tour-title');

    var spot = el('div', 'tour-spotlight');
    var bubble = el('div', 'tour-bubble');
    var arrow = el('div', 'tour-arrow');

    var counter = el('div', 'tour-counter');
    var title = el('h3', 'tour-title');
    title.id = 'tour-title';
    var body = el('p', 'tour-body');

    var close = el('button', 'tour-close');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close the tour');
    close.textContent = '×';
    close.addEventListener('click', function () { self.finish('closed'); });

    var back = el('button', 'btn btn-sm btn-outline-light tour-back', 'Back');
    back.type = 'button';
    back.addEventListener('click', function () { self.go(-1); });

    var skip = el('button', 'btn btn-sm btn-link tour-skip', 'Skip');
    skip.type = 'button';
    skip.addEventListener('click', function () { self.go(1); });

    var next = el('button', 'btn btn-sm btn-primary tour-next', 'Next');
    next.type = 'button';
    next.addEventListener('click', function () { self.go(1); });

    var actions = el('div', 'tour-actions');
    actions.appendChild(back);
    actions.appendChild(skip);
    actions.appendChild(next);

    bubble.appendChild(close);
    bubble.appendChild(counter);
    bubble.appendChild(title);
    bubble.appendChild(body);
    bubble.appendChild(actions);

    root.appendChild(spot);
    root.appendChild(arrow);
    root.appendChild(bubble);
    document.body.appendChild(root);
    document.body.classList.add('tour-open');

    this.nodes = {root: root, spot: spot, bubble: bubble, arrow: arrow,
                  counter: counter, title: title, body: body,
                  back: back, skip: skip, next: next};

    this.onKey = function (event) {
      if (event.key === 'Escape') { self.finish('closed'); }
      else if (event.key === 'ArrowRight') { self.go(1); }
      else if (event.key === 'ArrowLeft') { self.go(-1); }
      else if (event.key === 'Tab') { self.trapTab(event); }
    };
    document.addEventListener('keydown', this.onKey);
    window.addEventListener('resize', this.onResize);
    window.addEventListener('scroll', this.onResize, true);
  };

  /* The controls a keyboard can actually reach right now. Back is disabled on
   * the first step and Skip is hidden on the last, so the set changes per step
   * and cannot be captured once at build time. */
  Tour.prototype.reachable = function () {
    return Array.prototype.filter.call(
      this.nodes.bubble.querySelectorAll('button'),
      function (button) { return !button.disabled && !button.hidden; });
  };

  /* Keep Tab inside the tour.
   *
   * The root carries aria-modal, which tells a screen reader the rest of the
   * page is inert. Without this that is simply untrue: Tab walks straight out
   * into content that is dimmed, unreachable by mouse, and still focusable.
   */
  Tour.prototype.trapTab = function (event) {
    var items = this.reachable();
    if (!items.length) { return; }
    var first = items[0];
    var last = items[items.length - 1];
    var active = document.activeElement;

    if (!this.nodes.bubble.contains(active)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  Tour.prototype.go = function (delta) {
    var next = this.index + delta;
    if (next < 0) { return; }
    if (next >= this.steps.length) { this.finish('completed'); return; }
    this.index = next;
    this.show();
  };

  /* The drawer. Below the breakpoint the sidebar is off-canvas, so a step
   * pointing at a nav item is pointing at something that is not on screen. */
  Tour.prototype.setDrawer = function (wanted) {
    if (window.innerWidth >= DESKTOP_MIN) { return false; }
    var sidebar = document.querySelector('.sidebar');
    var overlay = document.getElementById('sidebar-overlay');
    if (!sidebar) { return false; }

    var open = sidebar.classList.contains('show');
    if (wanted === open) { return false; }
    sidebar.classList.toggle('show', wanted);
    if (overlay) { overlay.classList.toggle('show', wanted); }
    return true;                    // caller waits for the slide to finish
  };

  /* A nav step may also sit inside a collapsed group (F-49). Open it, or the
   * highlight lands on a zero-height element behind a folded panel. */
  Tour.prototype.revealGroup = function (target) {
    var panel = target.closest('.nav-group-items');
    if (!panel || panel.classList.contains('show')) { return false; }
    var toggle = document.querySelector('[data-bs-target="#' + panel.id + '"]');
    panel.classList.add('show');
    if (toggle) {
      toggle.classList.remove('collapsed');
      toggle.setAttribute('aria-expanded', 'true');
    }
    return true;
  };

  Tour.prototype.show = function () {
    var self = this;
    var step = this.steps[this.index];
    var target = document.querySelector(step.anchor);
    if (!target) { this.go(1); return; }        // vanished mid-tour

    var moved = this.setDrawer(!!step.nav);
    var opened = step.nav ? this.revealGroup(target) : false;

    var n = this.nodes;
    n.counter.textContent = (this.index + 1) + ' of ' + this.steps.length;
    n.title.textContent = step.title;
    n.body.textContent = step.body;
    n.back.disabled = this.index === 0;
    n.next.textContent = this.index === this.steps.length - 1 ? 'Done' : 'Next';
    // Nothing left to skip to on the last step; the button would be a second
    // Done wearing different words.
    n.skip.hidden = this.index === this.steps.length - 1;

    var settle = (moved || opened) ? 320 : 0;   // let the transition land first
    window.setTimeout(function () {
      target.scrollIntoView({block: 'center', behavior: 'smooth'});
      window.setTimeout(function () { self.place(target, step); }, settle ? 120 : 60);
    }, settle);
  };

  Tour.prototype.place = function (target, step) {
    var n = this.nodes;
    var box = target.getBoundingClientRect();

    n.spot.style.top = (box.top - 6) + 'px';
    n.spot.style.left = (box.left - 6) + 'px';
    n.spot.style.width = (box.width + 12) + 'px';
    n.spot.style.height = (box.height + 12) + 'px';

    var bubble = n.bubble.getBoundingClientRect();
    var side = step.placement || (window.innerWidth < DESKTOP_MIN ? 'bottom' : 'right');

    // Flip rather than overflow. A bubble half off the screen is worse than one
    // on the other side of the thing it describes.
    if (side === 'right' && box.right + GAP + bubble.width > window.innerWidth) { side = 'left'; }
    if (side === 'left' && box.left - GAP - bubble.width < 0) { side = 'bottom'; }
    if (side === 'bottom' && box.bottom + GAP + bubble.height > window.innerHeight) { side = 'top'; }
    if (side === 'top' && box.top - GAP - bubble.height < 0) { side = 'bottom'; }

    var top, left;
    if (side === 'right')       { top = box.top; left = box.right + GAP; }
    else if (side === 'left')   { top = box.top; left = box.left - bubble.width - GAP; }
    else if (side === 'top')    { top = box.top - bubble.height - GAP; left = box.left; }
    else                        { top = box.bottom + GAP; left = box.left; }

    // Keep it on screen whatever the anchor is doing near an edge.
    top = Math.max(8, Math.min(top, window.innerHeight - bubble.height - 8));
    left = Math.max(8, Math.min(left, window.innerWidth - bubble.width - 8));

    n.bubble.style.top = top + 'px';
    n.bubble.style.left = left + 'px';
    n.bubble.dataset.side = side;

    // The pointer, sitting between the bubble and what it points at.
    var arrow = n.arrow;
    arrow.dataset.side = side;
    if (side === 'right')      { arrow.style.top = (box.top + box.height / 2 - 7) + 'px'; arrow.style.left = (box.right + 1) + 'px'; }
    else if (side === 'left')  { arrow.style.top = (box.top + box.height / 2 - 7) + 'px'; arrow.style.left = (box.left - 13) + 'px'; }
    else if (side === 'top')   { arrow.style.top = (box.top - 13) + 'px'; arrow.style.left = (box.left + Math.min(box.width / 2, 40) - 7) + 'px'; }
    else                       { arrow.style.top = (box.bottom + 1) + 'px'; arrow.style.left = (box.left + Math.min(box.width / 2, 40) - 7) + 'px'; }

    n.next.focus({preventScroll: true});
  };

  Tour.prototype.reposition = function () {
    if (!this.nodes) { return; }
    var step = this.steps[this.index];
    var target = document.querySelector(step.anchor);
    if (target) { this.place(target, step); }
  };

  Tour.prototype.finish = function (reason) {
    if (!this.nodes) { return; }
    document.removeEventListener('keydown', this.onKey);
    window.removeEventListener('resize', this.onResize);
    window.removeEventListener('scroll', this.onResize, true);
    this.nodes.root.remove();
    this.nodes = null;
    document.body.classList.remove('tour-open');
    this.setDrawer(false);

    // Hand focus back where it was. `focus` is guarded because the element may
    // have been inside the drawer we have just closed.
    if (this.previousFocus && document.contains(this.previousFocus)) {
      try { this.previousFocus.focus({preventScroll: true}); } catch (e) { /* gone */ }
    }
    this.previousFocus = null;

    // Both endings count as seen. Someone who closed it on the second step has
    // told us something, and asking again tomorrow ignores the answer.
    if (this.options.recordUrl) {
      var body = new FormData();
      body.append('reason', reason);
      if (this.options.csrfToken) { body.append('csrf_token', this.options.csrfToken); }
      fetch(this.options.recordUrl, {
        method: 'POST', body: body, credentials: 'same-origin'
      }).catch(function () {
        // Offline, most likely. Losing the record means it is offered once
        // more, which is a far smaller failure than blocking the page.
      });
    }
  };

  window.TrackTrackTour = Tour;
}());
