# Frontend — Vite + React 19 + TypeScript + Tailwind 4

Loaded only when a session works in `frontend/`. Root rules still apply.

- Check: `npm run lint && npm run build` (oxlint; the build runs `tsc -b`).
- Dev: `npm run dev` (http://localhost:5173) with the backend on :8000 and `SIMBA_FAKE_LLM=1`.
- State lives in `App.tsx`; the SSE parser in `api.ts`; chat CRUD in `chatsApi.ts`.
- Read `docs/visual-style.md` before any visual change.
- A UI change needs a screenshot as proof (headless Playwright), not only a green build.
  Use scratch ports, never the owner's running dev servers.
- No tests yet (#12); add them with Vitest.
