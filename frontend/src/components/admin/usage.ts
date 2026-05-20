export function formatLastActive(value: string | null) {
  if (!value) {
    return "Never";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatLatency(value: number | null) {
  if (value === null) {
    return "NA";
  }

  return `${Math.round(value)} ms`;
}

export function formatCount(value: number) {
  return new Intl.NumberFormat().format(value);
}
