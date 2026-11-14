# I-ITSM frontend

React, Vite, TypeScript and Tailwind. It runs against a mock API until the FastAPI backend exists.

```bash
npm install
npm run dev
```

Open http://localhost:5173 and use the buttons under "Mock data" to open a console.

## Where things live

- `src/api/types.ts`: the API contract to agree with the backend.
- `src/api/client.ts`: the only code that talks to the server.
- `src/mocks/`: the mock backend (MSW). It follows the rules in `domain/`. Refreshing the page resets its data.

## Switching to the real backend

Set `VITE_USE_MOCK=false` in `.env.local`. Vite then proxies `/api` to `http://localhost:8000`, and the notification bell switches from polling to the live SSE stream.
