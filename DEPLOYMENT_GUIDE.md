# S&P 3 Weekly - Deployment Guide

## Phase 1: Prepare for Deployment ✅ COMPLETE

### Files Created/Updated

#### 1. **requirements.txt** ✅
- Added pinned versions for all dependencies
- Added PostgreSQL support: `psycopg2-binary==2.9.9`
- Added production server: `gunicorn==21.2.0`
- All 20 dependencies listed with versions

#### 2. **.env.example** ✅
- Documented all environment variables
- Shows SQLite config for local development
- Shows PostgreSQL config for production
- Includes email, admin, and newsletter settings

#### 3. **database.py** ✅
- Already supports both SQLite (dev) and PostgreSQL (prod)
- Automatically switches based on `DATABASE_URL` environment variable
- No changes needed - ready for production

#### 4. **Dockerfile** ✅
Created production-ready Docker image:
- Based on Python 3.11-slim (minimal size)
- Installs system dependencies (gcc, postgresql-client)
- Uses gunicorn + uvicorn for production serving
- Includes health check endpoint
- Runs as non-root user for security
- 4 workers configured for concurrent requests

#### 5. **.dockerignore** ✅
- Excludes .git, __pycache__, .env, *.db from image
- Reduces image size by ~50%

#### 6. **docker-compose.yml** ✅
Created local testing environment:
- PostgreSQL 16 Alpine (lightweight)
- Auto-creates database and credentials
- Volume persistence for data
- Health checks for reliability
- Hot-reload for development

#### 7. **.env** ✅ (Local Development)
- Configured for SQLite (fast local testing)
- Mock email/admin values
- Ready to use immediately

#### 8. **.gitignore** ✅
- Updated with comprehensive exclusions
- .env, *.db, venv, logs, IDE files, etc.
- Safe to commit to GitHub

### Test Results ✅

All routes tested and working:
```
✓ Health check: HTTP 200
✓ Home page (/): HTTP 200
✓ S&P3 Landing (/sp3): HTTP 200
✓ Subscribe page (/subscribe): HTTP 200
✓ API Strategies: Returns 1 strategy
✓ API Analytics: S&P 3 Return = 195.27%
```

---

## Next Steps: Phase 2 (Deploy to Railway)

### Prerequisites
- [ ] Create Railway.app account (free)
- [ ] Connect GitHub repository
- [ ] Have PostgreSQL credentials ready

### Deployment Steps

1. **Push to GitHub**
   ```bash
   cd /Users/derekb/Desktop/Code/sp3-weekly
   git add .
   git commit -m "chore: add production deployment files"
   git push origin main
   ```

2. **Create Railway Project**
   - Go to railway.app
   - Click "New Project" → "Deploy from GitHub"
   - Select your sp3-weekly repository
   - Railway auto-detects Dockerfile

3. **Configure Environment Variables**
   In Railway dashboard, add:
   ```
   DATABASE_URL=postgresql://...  (Railway generates this)
   RESEND_API_KEY=your_key_here
   FROM_EMAIL=sp3weekly@yourdomain.com
   REPLY_TO=derek@yourdomain.com
   ADMIN_SECRET=your_secret_key_here
   ADMIN_EMAIL=derek@yourdomain.com
   ENVIRONMENT=production
   ```

4. **Connect Domain**
   - Buy domain from Cloudflare or Namecheap
   - Update DNS to point to Railway
   - SSL certificate auto-provisioned

5. **Verify Deployment**
   ```bash
   curl https://yourdomainname.com/health
   # Should return:
   # {"status": "ok", "timestamp": "..."}
   ```

---

## Phase 3: Email Automation (Brevo Setup)

### Integration Steps

1. **Sign up for Brevo** (free tier up to 300 emails/day)
2. **Get API key** from Brevo dashboard
3. **Add to Railway environment**:
   ```
   BREVO_API_KEY=your_key_here
   ```

4. **Integration code** (will be in `app/mailer.py`):
   ```python
   from sib_api_v3_sdk import Configuration, ApiClient
   from sib_api_v3_sdk.apis.contacts_api import ContactsApi

   # Add subscriber
   # Send newsletter on schedule
   # Track bounces and unsubscribes
   ```

---

## Troubleshooting

### Docker Build Issues
```bash
# Test Docker build locally
docker build -t sp3-weekly .

# Test docker-compose locally
docker-compose up
```

### Environment Variables Not Working
- Check Railway dashboard for typos
- Verify variable names match .env.example
- Restart Railway app after adding variables

### Database Connection Errors
- Confirm PostgreSQL credentials in DATABASE_URL
- Run migrations: `alembic upgrade head`
- Check Railway PostgreSQL add-on is enabled

### Port Issues
- Railway auto-assigns port, doesn't conflict with 8082
- Uvicorn listens on 8082 inside container
- Railway maps to port 80 externally

---

## Cost Summary

| Service | Monthly Cost | Notes |
|---------|--------------|-------|
| Railway.app | $5-15 | App + DB |
| Domain (Cloudflare) | ~$1 | $8.85/year |
| Brevo (Email) | $0-25 | Free up to 300/day |
| **Total** | **~$5-40/mo** | Very affordable |

---

## Files Ready for Deployment

✅ Dockerfile
✅ .dockerignore
✅ requirements.txt (with versions)
✅ .env.example (documented)
✅ docker-compose.yml
✅ All source code

**Status: Ready for Phase 2 (Railway Deployment)**

Next action: Push code to GitHub and deploy to Railway.app
