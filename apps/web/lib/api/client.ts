import "server-only";

import { validatedApiOrigin, validatedApiPath } from "./boundary";

export class ApiResponseError extends Error {
  constructor(readonly status: number) {
    super(`Read API returned status ${status}`);
    this.name = "ApiResponseError";
  }
}

export async function fetchApi<T>(path: string): Promise<T> {
  const safePath = validatedApiPath(path);
  const origin = validatedApiOrigin(process.env.PYURI_INTERNAL_API_URL);
  const response = await fetch(`${origin}${safePath}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) {
    throw new ApiResponseError(response.status);
  }
  return (await response.json()) as T;
}
