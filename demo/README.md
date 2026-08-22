# The demo recorder

Records a walkthrough of the **real** application as a phone-shaped video.

```bash
python demo/record.py                       # against a local dev server
python demo/record.py --url https://your-app.onrender.com --email you@example.com
```

Out comes `demo/out/tracktrack-demo.mp4`, 9:16, H.264, captions already burned in.

## Why a script rather than a screen recording

Three reasons, in the order they matter:

1. **It is repeatable.** Change a page, run it again, and the demo is current. A
   hand-made recording rots the first time you move a button, and the dread of
   remaking it is why most product videos are a year out of date.
2. **It cannot fumble.** No mis-taps, no hunting for a menu, no cursor wandering
   while somebody thinks. Every pause is deliberate because every pause is a
   number in this file.
3. **It is the real interface.** Generated video cannot render your app - it
   renders a plausible painting of one, and the text melts. This is the actual
   page, actually rendering.

## What it does that a plain recording cannot

- **A cursor.** Browsers do not record one, so the script draws its own and
  glides it between targets. Without it, screens appear to change by themselves.
- **Captions on the page.** Burned in at record time, so there is no editing
  step and nothing to sync. The video is finished when the script finishes.
- **Deliberate pacing.** Real demos are too fast, because the person driving
  already knows where everything is. The timings here are set for somebody
  seeing it for the first time.

## Editing it

`SCENES` near the bottom is the whole film. Each scene is a caption, a page and
a list of actions. Reorder them, retime them, rewrite the captions - it is a
list, not a program.

## Voiceover

Record it separately and lay it over the finished MP4. The captions are timed to
the script in `demo/voiceover.txt`, so a read at a natural pace lands close
without much nudging.
