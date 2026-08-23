const formatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

export function formatCount(value: number): string {
  if (!Number.isSafeInteger(value) || value < 0) {
    return "—";
  }
  return formatter.format(value);
}

export function formatOptionalCount(value: number | null): string {
  return value === null ? "—" : formatCount(value);
}

export function formatScaledCount(value: number, scale: 1 | 100): string {
  if (!Number.isSafeInteger(value) || value < 0) {
    return "—";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: scale === 100 ? 2 : 0,
    minimumFractionDigits: 0,
  }).format(value / scale);
}

export function formatSignedCount(value: number | null): string {
  if (value === null || !Number.isSafeInteger(value)) {
    return "—";
  }
  const magnitude = formatter.format(Math.abs(value));
  return value > 0 ? `+${magnitude}` : value < 0 ? `−${magnitude}` : "0";
}

export function formatBasisPoints(value: number | null): string {
  if (value === null || !Number.isSafeInteger(value)) {
    return "—";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
    signDisplay: "exceptZero",
    style: "percent",
  }).format(value / 10_000);
}

export function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}
