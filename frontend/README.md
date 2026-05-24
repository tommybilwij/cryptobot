# Cryptobot Strategy Lab UI

Minimal Next.js dashboard for cryptobot. Read-only monitoring + a kill button.

## Dev

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3002.

## Pages

- `/` — landing
- `/oms` — OMS status + kill switch
- `/profiles` — placeholder
- `/live` — placeholder
- `/audit` — placeholder
- `/exchanges` — placeholder

## CORS

If the backend doesn't allow `http://localhost:3002`, add CORS middleware in
`backend/app/main.py`. Phase 19 leaves this as an ops setup step.
