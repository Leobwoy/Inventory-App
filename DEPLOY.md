# Deploying TrackTrack — Neon + Koyeb

Both free, neither with an expiry clock. Roughly 30 minutes end to end, most of
it waiting.

Order matters: **the database first**, because Koyeb needs its connection string
before the app will start.

---

## 1. The database — Neon

1. Sign up at **https://neon.tech** with GitHub.
2. Create a project:
   - **Name**: `tracktrack`
   - **Postgres version**: 16
   - **Region**: **Europe (Frankfurt)** — `aws-eu-central-1`
3. Copy the connection string it shows you. It looks like:

   ```
   postgresql://neondb_owner:XXXX@ep-something-123456.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

   Keep the `?sslmode=require`. Neon refuses unencrypted connections.

**Why Frankfurt and not somewhere closer.** West African undersea cables run
north to Europe. Traffic from Accra reaches Frankfurt faster than Johannesburg,
because "closer on a map" and "closer on the cable" are different things.

**Why not Render.** Its free Postgres deletes itself after 30 days. Neon's free
tier has no expiry — it sleeps when idle and wakes on the next request.

---

## 2. The app — Koyeb

1. Sign up at **https://koyeb.com** with GitHub.
2. **Create Web Service** → **GitHub** → authorise it → pick your repository.
3. Settings:
   - **Branch**: `main`
   - **Builder**: **Dockerfile** (not Buildpack — the repo has a Dockerfile that
     runs migrations at start)
   - **Instance**: **Free** (`eco-nano`)
   - **Region**: **Frankfurt** (`fra`) — same as the database
   - **Port**: `8000`
4. **Environment variables** — add both, marked **Secret**:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | the Neon string from step 1, in full |
   | `SECRET_KEY` | generate it — see below |

   Generate the key on your machine and paste the output:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   **The app will refuse to start without `SECRET_KEY`, on purpose.** It used to
   fall back to a default written in this repository. Anyone who had read the
   code could have forged a session cookie and signed in as any user of any
   business. A deploy that fails loudly is better than one that serves an app
   whose login means nothing.

5. **Deploy.** First build takes 3–5 minutes.

---

## 3. Create your account

The deploy runs `flask db upgrade`, which builds the schema and seeds the roles
and permissions. It does **not** create a user — you register the first one
through the app.

Open `https://<your-app>.koyeb.app/auth/register` and register your business.
That account becomes the Owner.

Then go to **Administration → Settings** and set your business name, address,
contact, logo, and the discount ceiling (it starts at 0, which means
discounting is switched off).

---

## 4. Check it worked

```
https://<your-app>.koyeb.app/sw.js          → JavaScript, not a 404
https://<your-app>.koyeb.app/manifest.json  → JSON
```

Then on an Android phone in Chrome, open the app and look for **Install app** in
the ⋮ menu. It should install with the TrackTrack icon and open without a
browser bar.

**This is the step that needs HTTPS.** A service worker will not register over
plain `http://` except on `localhost`, which is why the app cannot be shown as
installable from your machine.

To prove offline works: install it, turn on aeroplane mode, open it. You should
get the "No connection" page rather than a browser error — and if your plan
includes offline selling, you can record a sale and watch it sync when the
signal returns.

---

## What free actually gets you

| | Free tier | Runs out when |
|---|---|---|
| **Neon** | 0.5 GB storage, sleeps when idle | 0.5 GB is thousands of businesses' worth of rows |
| **Koyeb** | 1 service, 512 MB RAM, sleeps after inactivity | You need a second service, or the sleep becomes unacceptable |

**The sleep is the thing to know about.** Both tiers idle out. The first request
after a quiet period takes **10–30 seconds** while the container and database
wake up. Every request after that is normal.

For a demo, warn whoever is watching, or load a page a minute beforehand. For
real pilot users this is the first thing worth paying to remove — Koyeb's
smallest paid instance is about $2/month and does not sleep.

---

## When something goes wrong

**Build fails.** Koyeb → your service → **Logs** → Build. Almost always a
dependency; `requirements.txt` bounds every package rather than letting the host
resolve whatever it likes.

**App builds but will not start.** Check Runtime logs.
- `SECRET_KEY is not set` — you missed step 2.4. Deliberate.
- `could not connect to server` — `DATABASE_URL` is wrong, or `?sslmode=require`
  was dropped from the end.

**Registration says "Owner role not found".** Migrations did not run. Confirm the
builder is **Dockerfile**, not Buildpack — the Dockerfile's start command is what
runs `flask db upgrade`.

**"Not secure" or the login loops.** Both come from the proxy. Koyeb terminates
TLS and forwards plain HTTP, so the app uses `ProxyFix` to see the original
scheme. Without it Flask thinks every request is insecure and refuses to set the
session cookie it was told to mark `Secure`. This is already configured — if you
see it, `TRACKTRACK_ENV=production` is missing, which the Dockerfile sets.

**Installed app shows an old version.** The service worker caches the shell.
Bump `CACHE_VERSION` in `static/sw.js` when you change a stylesheet or script;
old caches are deleted on activation.

---

## Afterwards

- **Point a domain at it.** Koyeb → Settings → Domains. A real domain matters
  more than it should when selling to a business.
- **Take a backup before your first real customer.** Neon has restore points,
  and the app has a per-tenant CSV export under **Backup**.
- **Watch the first cold start with a customer present.** It is the single
  worst first impression the free tier can make.
