const DEFAULT_API_ORIGIN = "http://127.0.0.1:8000";
const ALLOWED_API_ORIGINS = new Set([
  "http://127.0.0.1:8000",
  "http://localhost:8000",
  "http://api:8000",
]);

export function validatedApiOrigin(configured?: string): string {
  const parsed = new URL(configured ?? DEFAULT_API_ORIGIN);
  const isRailwayPrivateOrigin =
    parsed.protocol === "http:" &&
    parsed.hostname.endsWith(".railway.internal") &&
    /^\d{1,5}$/u.test(parsed.port);
  if (
    (!ALLOWED_API_ORIGINS.has(parsed.origin) && !isRailwayPrivateOrigin) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("PYURI_INTERNAL_API_URL is outside the private API boundary");
  }
  return parsed.origin;
}

export function validatedApiPath(path: string): string {
  if (
    !path.startsWith("/api/v1/") ||
    path.length > 2_048 ||
    path.includes("://") ||
    path.includes("\\") ||
    path.includes("#") ||
    /[\u0000-\u001f\u007f]/u.test(path)
  ) {
    throw new Error("API client accepts only bounded versioned relative read paths");
  }
  return path;
}
