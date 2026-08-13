# Cascade

Paste a link and get the file. The server downloads it for you — over several
connections at once, resuming if it drops, resolving the real link behind the
page — and hands it to your browser. Then it deletes its copy.

That last part is the whole idea: the server is a place to pass through, not a
warehouse. There is no folder to administer and no files piling up on someone
else's disk.

There is no login either. You arrive and you use it.

---

## How it works for the person using it

**Paste → choose → receive.**

1. You paste one or more URLs, one per line.
2. Cascade looks at what sits behind each one: a direct file, an open directory
   with twenty files inside, a video with six qualities. It shows you what it
   found.
3. You untick what you don't want, pick a quality where there is one, and
   confirm.
4. The file downloads to the server and, the moment it finishes, your browser
   pulls it into your downloads folder on its own.

The history lives in your browser, tied to an anonymous token. Registering is
**optional** and buys one thing: keeping that list and seeing it from another
device.

## Running it

Requires Docker.

```bash
cp .env.example .env      # put a real password in POSTGRES_PASSWORD
docker compose up -d --build
```

It comes up on **http://127.0.0.1:8080**.

It listens on localhost only, on purpose. Since there is no login, exposing it
to the network gives anyone the ability to queue downloads and change the
engine limits. Opening it up has to be a decision:

```bash
BIND_ADDRESS=0.0.0.0    # in .env
```

Read [What isn't there yet](#what-isnt-there-yet) before you do.

## Deploying it somewhere

The root `Dockerfile` builds the whole thing into one image: the SPA is
compiled and served by FastAPI itself, so there is one process on one port and
no proxy in between. It is what platforms that deploy a single service from a
repository expect — Railway, Fly, Render. `docker compose` keeps using the two
per-service Dockerfiles with nginx in front, which is the right shape locally.

On Railway specifically:

1. New project → deploy from this repo. `railway.json` already selects the
   Dockerfile builder and points the health check at `/health`.
2. Add a **Postgres** database to the project.
3. On the web service, set `DATABASE_URL` to reference it —
   `${{Postgres.DATABASE_URL}}`. The app rewrites the scheme to asyncpg on the
   way in, so the platform's variable works untouched.
4. Attach a **volume mounted at `/downloads`**. Without it, a redeploy throws
   away whatever was mid-flight. The engine resumes interrupted downloads, but
   only if the partial file is still there.

`PORT` is injected by the platform and the image honours it. Migrations run on
boot.

Sizing is the thing to watch: files pass through the disk on their way to the
browser, so the volume has to fit the largest file you expect plus whatever is
in flight, and every byte is paid for twice in egress — once fetching it, once
handing it over.

**Before putting it on a public URL, read the section at the end.** There is no
login by design, and a public address turns each of those open edges into
something anyone can reach.

## What's inside

Three containers: `frontend` (nginx serving the SPA and proxying to the
backend, so the WebSocket needs no CORS), `backend` (FastAPI) and `postgres`.

The backend runs three loops in parallel over one shared stop event:

| Loop | What it does |
|---|---|
| scheduler | takes queued items and downloads them in parallel chunks |
| crawl | expands the pasted links into concrete files |
| sweep | frees what has been delivered, and what nobody came back for |

**The download engine** splits each file into chunks and requests them with
`Range`. It records progress in the database only after flushing the buffer to
disk, so a restart midway resumes from a byte that is genuinely written rather
than one that was only in memory. There is a global speed limit via a token
bucket.

**Separate qualities** (YouTube's 1080p arrives as two tracks) are downloaded as
two sibling items and joined with `ffmpeg -c copy`, without re-encoding. The
audio track is never shown as a separate download: it is a means, not something
the user asked for.

**Deletion** has two triggers: 30 minutes after you retrieve the file — not
zero, because if your download breaks at 90% you want to retry — and a 24-hour
ceiling for anything nobody came for.

### Layout

```
backend/app/
  api/          endpoints: /packages /crawl-jobs /settings /account
  engine/       scheduler, chunker, downloader, rate limiter, merge
  crawler/      link expansion with bounded recursion
  plugins/      one file per hoster
  ws/           live progress feed
frontend/src/
  components/   FlowRail (the meter), Masthead, dialogs, rows
  pages/        Dashboard, LinkGrabber, PackageDetail, Settings, Account
docs/superpowers/   specs and plans for both phases
```

The fonts are served from `frontend/public/fonts`, not a CDN: a tool whose
argument is that it keeps nothing of yours cannot leak every visit to a third
party.

## Plugins

Each hoster is a file in `backend/app/plugins/` exposing `PLUGIN`. The registry
discovers them at startup: adding a hoster means adding a file, not editing a
list.

| Plugin | Covers |
|---|---|
| `ytdlp` | ~1750 video sites, with their qualities |
| `open_directory` | Apache/nginx indexes, recursive up to 3 levels |
| `pixeldrain` | files and albums |
| `direct` | any URL; goes last and closes the list |

When a site refuses the default player client - YouTube answers "Sign in to
confirm you're not a bot" to anything coming from a datacenter address - the
plugin walks a list of alternatives until one gets through, and remembers which
one worked. Only a block moves on to the next; a video that is simply gone is
reported as gone. `YTDLP_EXTRACTOR_ARGS` pins a specific client when you want
to override the search entirely.

When every client is refused, the address is the problem and no code change
fixes it. Two ways out, both configured rather than built in:

**Cookies**, pasted into Settings in the running app. A jar in Netscape format
authenticates the request, which is what the block is asking for. It lives in
the settings row rather than the environment because these expire every few
weeks: replacing one is routine maintenance and must not need a redeploy. The
API reports only whether a jar is stored, never its contents.

**A proxy**, through `OUTBOUND_PROXY`. A residential one is what actually
solves a datacenter block. It stays an environment variable because it is
infrastructure - which network path the server takes - like `DOWNLOAD_ROOT`.

The proxy covers both layers on purpose: applied to only one, resolution
succeeds from an address the site tolerates and the download then runs from the
one it doesn't, surfacing as a broken link rather than a block.

Use a throwaway Google account for the cookies, never a real one. This service
has no login, so whoever finds the URL downloads as that account — and it is
that account that gets suspended if someone abuses it. They also expire every
few weeks.

The contract is two operations. `crawl(url)` runs when the link is pasted and
returns which files sit behind it. `resolve(url, format_id)` runs just before
downloading, because most hosters' direct URLs expire within minutes and one
resolved at paste time would already be dead by the time it reached the queue.

Failures are declared with types — `LinkDead`, `UnsupportedLink`, `RateLimited`
— and each leads to a different decision: discard, keep trying other plugins,
or reschedule for later. Everything else is wrapped and bounded by a timeout: a
hung plugin does not keep a slot forever.

## Configuration

From the environment (`.env`):

| Variable | Default | What for |
|---|---|---|
| `POSTGRES_PASSWORD` | `cascade` | change it |
| `BIND_ADDRESS` | `127.0.0.1` | `0.0.0.0` opens it to the network |
| `OUTBOUND_PROXY` | empty | proxy for every outbound fetch |
| `YTDLP_EXTRACTOR_ARGS` | empty | pins a yt-dlp player client |

From the UI, under Settings — and these apply to the whole engine, not per
user: simultaneous downloads (3), simultaneous checks (5), chunks per file (4)
and a speed limit in KB/s (unlimited). The cookie jar for blocked sites is
there too.

Retention times are tuned through the environment:
`RETRIEVAL_GRACE_MINUTES` (30) and `MAX_RETENTION_HOURS` (24).

## Development

```bash
# backend
cd backend
pip install -e ".[dev]"
pytest                     # tests marked 'live' are excluded
pytest -m live             # those hit real sites; run them by hand

# frontend
cd frontend
npm install
npm test
npm run dev                # Vite dev server, proxying to the backend on :8000
```

The backend tests run on in-memory SQLite while production is Postgres; keep
that in mind when touching raw SQL or column types, which is exactly where the
difference bites.

The database migrates itself when the container starts (`alembic upgrade head`).

## What isn't there yet

Honesty about the edges, because the stated goal is for this to be a public
tool and it isn't one yet:

- **SSRF.** The server fetches whatever URL it is given. Nothing today stops it
  requesting `http://169.254.169.254/` or anything else on the internal
  network. It is the main reason the bind address is localhost.
- **No quotas.** Nobody limits how much a visitor queues or how much disk they
  use.
- **Engine settings are global** and anyone reaching the UI can change them.
  They should be operator-only.

## License

MIT. See [LICENSE](LICENSE).
