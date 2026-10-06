# AttendSure — Phase 1

Predictive attendance early-warning system for engineering colleges.

## Run locally

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

cd ../frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Demo student: `student@demo.com` / `demo123`.

The Phase 1 notifier is intentionally a mock. It stores messages in the database and logs the configured recipient (`WHATSAPP_TEST_PHONE`, defaulting to `+917391936044`); set `WHATSAPP_MODE=twilio` plus provider credentials before attempting real delivery.

## Deployment

Deploy `frontend/` as the Vercel project root. In Vercel, set `VITE_API_URL` to the public URL of the FastAPI backend followed by `/api`. Deploy the backend separately with PostgreSQL and set `FRONTEND_URL` to the final Vercel URL.
