# S&P 3 Weekly

Automated newsletter for the S&P 3 investment strategy — buy $100 each of the top 3 S&P 500 companies by market cap, every Friday.

## Quick Start

```bash
# 1. Clone and install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure env
cp .env.example .env
# Fill in RESEND_API_KEY, ADMIN_SECRET, etc.

# 3. Run locally
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 for the subscribe page, http://localhost:8000/admin?secret=YOUR_SECRET for the admin dashboard.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `RESEND_API_KEY` | Resend API key (get one at resend.com) |
| `FROM_EMAIL` | Verified sender email |
| `REPLY_TO` | Reply-to address |
| `ADMIN_SECRET` | Secret for admin dashboard access |
| `ADMIN_EMAIL` | Your email for previews/alerts |
| `DATABASE_URL` | SQLite (dev) or PostgreSQL (prod) |

## Deploy to Railway

1. Push code to GitHub
2. Create a new Railway project → connect your repo
3. Add a PostgreSQL database plugin
4. Set all environment variables in Railway dashboard
5. Add `RAILWAY_TOKEN` to GitHub repo secrets for CI/CD

## Architecture

```
app/
├── main.py       — FastAPI entry point + lifespan
├── fetcher.py    — Market cap data (yfinance → slickcharts → fallback)
├── database.py   — SQLAlchemy models (Subscriber, WeeklyPick)
├── newsletter.py — Jinja2 HTML email generator
├── mailer.py     — Resend API email sender
├── scheduler.py  — APScheduler Friday 6AM ET cron job
└── admin.py      — Admin API routes + dashboard
templates/
├── newsletter.html  — Email template (inline styles, table layout)
├── subscribe.html   — Public landing page
└── admin.html       — Internal admin dashboard
```

## Running Tests

```bash
pytest tests/ -v
```
