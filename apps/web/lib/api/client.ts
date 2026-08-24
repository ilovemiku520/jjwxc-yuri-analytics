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

export async function postApi<T>(path: string, body: unknown): Promise<T> {
  const safePath = validatedApiPath(path);
  const origin = validatedApiOrigin(process.env.PYURI_INTERNAL_API_URL);
  const operationToken = process.env.PYURI_COHORT_IMPORT_TOKEN;
  if (!operationToken) throw new Error("Internal cohort import is disabled");
  const response = await fetch(`${origin}${safePath}`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Pyuri-Internal-Operation": operationToken,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) {
    throw new ApiResponseError(response.status);
  }
  return (await response.json()) as T;
}

export async function fetchInternalApi<T>(path: string): Promise<T> {
  const safePath = validatedApiPath(path);
  const origin = validatedApiOrigin(process.env.PYURI_INTERNAL_API_URL);
  const operationToken = process.env.PYURI_COHORT_IMPORT_TOKEN;
  if (!operationToken) throw new Error("Internal operation is disabled");
  const response = await fetch(`${origin}${safePath}`, {
    cache: "no-store",
    headers: { Accept: "application/json", "X-Pyuri-Internal-Operation": operationToken },
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) throw new ApiResponseError(response.status);
  return (await response.json()) as T;
}
