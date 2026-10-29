/**
 * NEXT_PUBLIC_API_BASE: "http://localhost:8000" in dev (.env.development),
 * "/api" in production (.env.production; nginx proxies it to the backend).
 */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "/api").replace(/\/+$/, "");

/**
 * Optional. Only needed when calling an API that has API_KEYS set WITHOUT the nginx proxy.
 * Anything in NEXT_PUBLIC_* ships to the browser, so never set this for a public site;
 * the nginx proxy injects the key server-side instead.
 */
export const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";
