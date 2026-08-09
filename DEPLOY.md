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

## 2. The app — Render

> **Koyeb was the original plan and is no longer usable.** It has been acquired
> by Mistral; new signups land on a marketing page with no way to create a
> service. Render replaces it.
>
> Render was rejected first time round for one reason: its free Postgres
> **deletes itself after 30 days**. That objection does not apply here, because
> the database is Neon. We are only using Render to run the container.

1. Sign up at **https://render.com** with GitHub. No card required.
2. **New** → **Web Service** → connect your repository.
3. Settings:
   - **Branch**: `main`
   - **Language / Runtime**: **Docker** (Render detects the Dockerfile; do not
     pick Python, or it will skip the migration step that runs at start)
   - **Instance Type**: **Free**
   - **Region**: **Frankfurt** — same as the database
   - **Health Check Path**: `/offline`

   Leave build and start commands empty. The Dockerfile owns both, and its start
   command is what runs `flask db upgrade`.

   `/offline` as the health check is deliberate: it is the one route that returns
   200 with no login and no database. Render's default probe hits `/`, which
   redirects to the login page, and a 302 reads as a failed health check.
4. **Environment variables** — add both, marked **Secret**:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | the Neon string from step 1, in full, keeping `?sslmode=require` |
   | `SECRET_KEY` | generate it — see below |

   Render injects `PORT` itself; the Dockerfile already binds to it, so do not
   set it by hand.

   Then, to take mobile money payments, add these too:

   | Name | Value |
   |---|---|
   | `MOMO_NUMBER` | the wallet customers send to, e.g. `0244000111` |
   | `MOMO_NAME` | the name that shows when they send, so they know it is you |
   | `MOMO_NETWORK` | `MTN`, `Telecel` or `AirtelTigo` (defaults to `MTN`) |

   The wallet number is configuration and not code because it is a personal
   phone number and this repository is public.



   Generate the key on your machine and paste the output:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   **The app will refuse to start without `SECRET_KEY`, on purpose.** It used to
   fall back to a default written in this repository. Anyone who had read the
   code could have forged a session cookie and signed in as any user of any
   business. A deploy that fails loudly is better than one that serves an app
   whose login means nothing.

5. **Create Web Service.** First build takes 5–10 minutes.

### 2b. Your console account

Confirming payments happens in a separate console at `/platform/login`, with its
own accounts. You do **not** need a business to use it — the person who runs
TrackTrack is not a customer of it.

There is no signup page, deliberately: the set of people who can confirm
payments should be exactly the set who can already deploy the app. So the first
account is made from a shell.

Render's free tier has no shell, so run it from your machine against the live
database:

```bash
DATABASE_URL="<your Neon string>" flask create-platform-admin
```

It prompts for email, name and password — nothing sensitive on the command line.
Use at least 12 characters; that account can change what every business has paid
for.

Then sign in at `https://<your-app>.onrender.com/platform/login`.

**If you ever cannot get to the console**, the same job can be done from a
terminal:

```bash
DATABASE_URL="<your Neon string>" flask pending-payments
DATABASE_URL="<your Neon string>" flask confirm-payment <reference>
DATABASE_URL="<your Neon string>" flask reject-payment <reference>
```

The reference is what the customer submitted — for mobile money, the transaction
ID their network texted them. `pending-payments` lists them.

### 2c. Letting trials and plans expire on their own

Without this, a trial that ended three weeks ago still reads "Trial" in your
console. Nobody is over-served — what a business may actually *do* is worked out
from the dates on every page load, so an expired trial stops granting paid
features the moment it expires whether or not any of this is set up. What you
get here is the stored status catching up, so the console tells you the truth
and reminders have something to fire on.

1. Make a secret, on your own machine:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. On Render, add it as `CRON_SECRET` (marked **Secret**).
3. On GitHub, go to **Settings → Secrets and variables → Actions → New
   repository secret** and add two:

   | Name | Value |
   |---|---|
   | `CRON_SECRET` | the same string you just gave Render |
   | `APP_URL` | `https://inventory-app-svrn.onrender.com` — no trailing slash |

`.github/workflows/subscriptions.yml` then calls the app at 02:10 UTC daily. To
test it now, open **Actions → Subscriptions → Run workflow**.

If you skip this entirely, nothing breaks: the check also runs once a day for
each business that opens the app, which covers everyone still using it. The
schedule exists to catch the ones who have stopped — the accounts worth a phone
call. And you can always run it by hand:

```bash
flask subscriptions-reconcile --dry-run
```


### If you would rather not have the app sleep

Render's free instance spins down after 15 minutes idle and takes **about a
minute** to wake — noticeably worse than Koyeb's was. Two ways out:

- **Render Starter, $7/month.** Same service, no sleep, one click.
- **Fly.io.** A small always-on allowance that covers one instance of this size,
  and it is Docker-native so the same Dockerfile works. It requires a card on
  file even for the free allowance, which is the only reason it is not the
  recommendation here.

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
| **Render** | 1 web service, 512 MB RAM, sleeps after 15 min idle | The ~1 minute cold start stops being acceptable in front of a customer |

**The sleep is the thing to know about.** Both tiers idle out. The first request
after a quiet period takes **10–30 seconds** while the container and database
wake up. Every request after that is normal.

For a demo, warn whoever is watching, or load a page a minute beforehand. For
real pilot users this is the first thing worth paying to remove — Koyeb's
smallest paid instance is about $2/month and does not sleep.

---

## When something goes wrong

**Build fails.** Render → your service → **Logs**. Almost always a
dependency; `requirements.txt` bounds every package rather than letting the host
resolve whatever it likes.

**App builds but will not start.** Check Runtime logs.
- `SECRET_KEY is not set` — you missed step 2.4. Deliberate.
- **The Subscriptions workflow fails with 404** — `CRON_SECRET` on GitHub does
  not match the one on Render, or Render does not have it set at all. The
  endpoint returns 404 rather than 403 so that an unconfigured install does not
  advertise itself.
- **A status in the console looks stuck** — it is not load-bearing. Run
  `flask subscriptions-reconcile --dry-run` to see what should move.
- `could not connect to server` — `DATABASE_URL` is wrong, or `?sslmode=require`
  was dropped from the end.

**Registration says "Owner role not found".** Migrations did not run. Confirm the
runtime is **Docker**, not Python — the Dockerfile's start command is what runs
`flask db upgrade`.

**"Not secure" or the login loops.** Both come from the proxy. Render terminates
TLS and forwards plain HTTP, so the app uses `ProxyFix` to see the original
scheme. Without it Flask thinks every request is insecure and refuses to set the
session cookie it was told to mark `Secure`. This is already configured — if you
see it, `TRACKTRACK_ENV=production` is missing, which the Dockerfile sets.

**Installed app shows an old version.** The service worker caches the shell.
Bump `CACHE_VERSION` in `static/sw.js` when you change a stylesheet or script;
old caches are deleted on activation.

---

## Afterwards

- **Point a domain at it.** Render → Settings → Custom Domains. A real domain matters
  more than it should when selling to a business.
- **Take a backup before your first real customer.** Neon has restore points,
  and the app has a per-tenant CSV export under **Backup**.
- **Watch the first cold start with a customer present.** It is the single
  worst first impression the free tier can make.
