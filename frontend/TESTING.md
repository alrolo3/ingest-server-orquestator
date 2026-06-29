# Frontend Testing

The frontend uses Vitest, jsdom, React Testing Library, and
`@testing-library/user-event`.

## Commands

Run from `frontend/`:

```bash
npm test
npm run test:run
npm run test:watch
npm run test:coverage
npm run test:ui
```

`npm run test:run` is the CI-style command. Coverage output is written by
Vitest when `npm run test:coverage` is used.

## Test Layout

Tests live next to the code they cover:

```text
src/components/**/__tests__/*.test.tsx
src/hooks/__tests__/*.test.ts
src/pages/__tests__/*.test.tsx
src/utils/__tests__/*.test.ts
src/test/setup.ts
src/test/utils.tsx
```

## Shared Setup

`src/test/setup.ts` runs after each test and provides browser mocks for:

- `window.matchMedia`
- `ResizeObserver`
- `IntersectionObserver`
- `import.meta.env.VITE_API_VDB_URL`
- KUI/CSS imports used by components

`src/test/utils.tsx` re-exports React Testing Library and replaces `render`
with a wrapper that provides:

- `BrowserRouter`
- `QueryClientProvider`

Use it for components that depend on routing or React Query:

```tsx
import { render, screen } from '@/test/utils';
```

Use React Testing Library directly only for components that do not need those
providers.
