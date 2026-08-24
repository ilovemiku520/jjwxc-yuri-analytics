export interface LogMomentCorrelationStats {
  pairedCount: number;
  xMean: number | null;
  yMean: number | null;
  xSecondCentralMoment: number | null;
  ySecondCentralMoment: number | null;
  covariance: number | null;
  pearson: number | null;
  spearman: number | null;
  pearsonConfidenceLow: number | null;
  pearsonConfidenceHigh: number | null;
}

const EMPTY_STATS: LogMomentCorrelationStats = {
  pairedCount: 0,
  xMean: null,
  yMean: null,
  xSecondCentralMoment: null,
  ySecondCentralMoment: null,
  covariance: null,
  pearson: null,
  spearman: null,
  pearsonConfidenceLow: null,
  pearsonConfidenceHigh: null,
};

function mean(values: number[]): number {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function clampCorrelation(value: number): number {
  return Math.max(-1, Math.min(1, value));
}

function pearsonFromValues(xValues: number[], yValues: number[]): number | null {
  if (xValues.length < 2 || xValues.length !== yValues.length) return null;
  const xMean = mean(xValues);
  const yMean = mean(yValues);
  const xMoment = mean(xValues.map((value) => (value - xMean) ** 2));
  const yMoment = mean(yValues.map((value) => (value - yMean) ** 2));
  if (xMoment === 0 || yMoment === 0) return null;
  const covariance = mean(
    xValues.map((value, index) => (value - xMean) * (yValues[index] - yMean)),
  );
  return clampCorrelation(covariance / Math.sqrt(xMoment * yMoment));
}

function averageRanks(values: number[]): number[] {
  const ordered = values
    .map((value, index) => ({ value, index }))
    .sort((left, right) => left.value - right.value || left.index - right.index);
  const ranks = Array<number>(values.length);
  let start = 0;
  while (start < ordered.length) {
    let end = start + 1;
    while (end < ordered.length && ordered[end].value === ordered[start].value) end += 1;
    const averageRank = (start + 1 + end) / 2;
    for (let index = start; index < end; index += 1) {
      ranks[ordered[index].index] = averageRank;
    }
    start = end;
  }
  return ranks;
}

function fisherConfidenceInterval(
  coefficient: number | null,
  pairedCount: number,
): [number | null, number | null] {
  if (coefficient === null || pairedCount < 4) return [null, null];
  const bounded = Math.max(-0.999999, Math.min(0.999999, coefficient));
  const fisherZ = Math.atanh(bounded);
  const margin = 1.96 / Math.sqrt(pairedCount - 3);
  return [Math.tanh(fisherZ - margin), Math.tanh(fisherZ + margin)];
}

export function analyzeLogMomentCorrelation(
  pairs: Array<[number, number]>,
): LogMomentCorrelationStats {
  const transformed = pairs
    .filter(
      ([x, y]) => Number.isFinite(x) && Number.isFinite(y) && x >= 0 && y >= 0,
    )
    .map(([x, y]) => [Math.log1p(x), Math.log1p(y)] as const);
  if (!transformed.length) return EMPTY_STATS;

  const xValues = transformed.map(([x]) => x);
  const yValues = transformed.map(([, y]) => y);
  const xMean = mean(xValues);
  const yMean = mean(yValues);
  const xSecondCentralMoment = mean(xValues.map((value) => (value - xMean) ** 2));
  const ySecondCentralMoment = mean(yValues.map((value) => (value - yMean) ** 2));
  const covariance = mean(
    transformed.map(([x, y]) => (x - xMean) * (y - yMean)),
  );
  const pearson = pearsonFromValues(xValues, yValues);
  const spearman = pearsonFromValues(averageRanks(xValues), averageRanks(yValues));
  const [pearsonConfidenceLow, pearsonConfidenceHigh] = fisherConfidenceInterval(
    pearson,
    transformed.length,
  );

  return {
    pairedCount: transformed.length,
    xMean,
    yMean,
    xSecondCentralMoment,
    ySecondCentralMoment,
    covariance,
    pearson,
    spearman,
    pearsonConfidenceLow,
    pearsonConfidenceHigh,
  };
}
