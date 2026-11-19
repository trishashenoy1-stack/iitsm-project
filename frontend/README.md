# I-ITSM frontend

React, Vite, TypeScript and Tailwind. Separate screens for employees, technicians and administrators.

```bash
npm install
npm run dev
```

Open http://localhost:5173. `npm run dev` talks to the real FastAPI backend: `.env.development`
sets `VITE_USE_MOCK=false`, and Vite proxies `/api` to `http://localhost:8000` (override with
`API_URL`). Start the backend first (see the main README). The notification bell uses the live
SSE stream.

## Offline mock

To work on the UI without the backend, create `.env.development.local` with
`VITE_USE_MOCK=true`. A mock API (MSW) then answers in the browser, and the login page shows
buttons under "Mock data" to open each role's console. Refreshing the page resets its data.

## Where things live

- `src/api/types.ts`: the API contract shared with the backend.
- `src/api/client.ts`: the only code that talks to the server.
- `src/pages/employee`, `technician`, `admin`: one folder per role.
- `src/mocks/`: the mock backend (MSW), used only in mock mode.
