# Contrast verification

Tests cannot see "ugly", and they cannot see contrast at all — this is how each
redesigned page gets checked in both themes before it ships.

    python design/verify/capture.py <port>     # renders every page in both themes
    # then open  /static/_sweep.html  in the preview and read the output

`capture.py` renders each page server-side once per theme (rather than flipping
the attribute in the browser, which measures a page dressed in clothes it was
not rendered for) and rewrites every stylesheet link with a cache-buster.

Both files are copied into `static/` at run time because the sweep loads the
captured pages in iframes and must be same-origin. `static/_shot/` and
`static/_sweep.html` are gitignored.

**Why so much cache-busting.** Three separate readings during Stage 3 were of
stale bytes — a cached capture, a cached stylesheet, and a cached copy of the
sweep itself after `capture.py` deleted it from disk. Each produced a plausible
number describing an older build, and one of them sent me chasing a bug that was
already fixed. The sweep now prints the stylesheet version it measured against,
so a stale reading announces itself.
