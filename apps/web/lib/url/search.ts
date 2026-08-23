export type RawSearchParams = Record<string, string | string[] | undefined>;

export function firstSearchValue(
  value: string | string[] | undefined,
  maxLength = 255,
): string | undefined {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (candidate === undefined) {
    return undefined;
  }
  const normalized = candidate.trim();
  if (!normalized || normalized.length > maxLength || /[\u0000-\u001f\u007f]/u.test(normalized)) {
    return undefined;
  }
  return normalized;
}

export function allowedSearchValue<T extends string>(
  value: string | string[] | undefined,
  allowed: readonly T[],
): T | undefined {
  const candidate = firstSearchValue(value);
  return candidate && (allowed as readonly string[]).includes(candidate)
    ? (candidate as T)
    : undefined;
}

export function boundedIntegerSearchValue(
  value: string | string[] | undefined,
  minimum: number,
  maximum: number,
  fallback: number,
): number {
  const candidate = firstSearchValue(value, 16);
  if (!candidate || !/^\d+$/u.test(candidate)) {
    return fallback;
  }
  const parsed = Number(candidate);
  return Number.isSafeInteger(parsed) && parsed >= minimum && parsed <= maximum
    ? parsed
    : fallback;
}

export function pageHref(
  pathname: string,
  values: Record<string, string | undefined>,
): string {
  if (!pathname.startsWith("/") || pathname.startsWith("//")) {
    throw new Error("pagination pathname must be local");
  }
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value) {
      query.set(key, value);
    }
  }
  const rendered = query.toString();
  return rendered ? `${pathname}?${rendered}` : pathname;
}

export function safeRouteSegment(value: string, maxLength = 255): string | null {
  if (!value || value.length > maxLength || /[\u0000-\u001f\u007f/\\]/u.test(value)) {
    return null;
  }
  return value;
}
