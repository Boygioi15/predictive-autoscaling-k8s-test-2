type LabelValue = string | number;
type Labels = Record<string, LabelValue>;

const HTTP_DURATION_BUCKETS = [0.05, 0.1, 0.3, 0.5, 1, 2, 5];
const IO_DURATION_BUCKETS = [0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 1];

class CounterMetric {
  private readonly values = new Map<string, { labels: Labels; value: number }>();

  constructor(
    private readonly name: string,
    private readonly help: string,
  ) {}

  inc(labels: Labels, value = 1): void {
    const key = labelsKey(labels);
    const existing = this.values.get(key);

    if (existing) {
      existing.value += value;
      return;
    }

    this.values.set(key, {
      labels: { ...labels },
      value,
    });
  }

  render(): string {
    const lines = [`# HELP ${this.name} ${this.help}`, `# TYPE ${this.name} counter`];

    for (const entry of this.values.values()) {
      lines.push(`${this.name}${renderLabels(entry.labels)} ${entry.value}`);
    }

    return lines.join('\n');
  }
}

class HistogramMetric {
  private readonly values = new Map<
    string,
    {
      labels: Labels;
      bucketCounts: number[];
      count: number;
      sum: number;
    }
  >();

  constructor(
    private readonly name: string,
    private readonly help: string,
    private readonly buckets: number[],
  ) {}

  observe(labels: Labels, value: number): void {
    const key = labelsKey(labels);
    let existing = this.values.get(key);

    if (!existing) {
      existing = {
        labels: { ...labels },
        bucketCounts: new Array(this.buckets.length).fill(0),
        count: 0,
        sum: 0,
      };
      this.values.set(key, existing);
    }

    for (let index = 0; index < this.buckets.length; index++) {
      if (value <= this.buckets[index]) {
        existing.bucketCounts[index]++;
      }
    }

    existing.count++;
    existing.sum += value;
  }

  render(): string {
    const lines = [`# HELP ${this.name} ${this.help}`, `# TYPE ${this.name} histogram`];

    for (const entry of this.values.values()) {
      for (let index = 0; index < this.buckets.length; index++) {
        lines.push(
          `${this.name}_bucket${renderLabels({
            ...entry.labels,
            le: this.buckets[index],
          })} ${entry.bucketCounts[index]}`,
        );
      }

      lines.push(
        `${this.name}_bucket${renderLabels({ ...entry.labels, le: '+Inf' })} ${entry.count}`,
      );
      lines.push(`${this.name}_sum${renderLabels(entry.labels)} ${entry.sum}`);
      lines.push(`${this.name}_count${renderLabels(entry.labels)} ${entry.count}`);
    }

    return lines.join('\n');
  }
}

const httpRequestsTotal = new CounterMetric(
  'http_requests_total',
  'Total HTTP requests handled by the IO service',
);
const httpRequestDuration = new HistogramMetric(
  'http_request_duration_seconds',
  'HTTP request duration in seconds for the IO service',
  HTTP_DURATION_BUCKETS,
);
const ioFileOperationsTotal = new CounterMetric(
  'io_file_operations_total',
  'Total completed file I/O operations',
);
const ioFileBytesTotal = new CounterMetric(
  'io_file_bytes_total',
  'Total bytes transferred by the file I/O workload',
);
const ioFileDuration = new HistogramMetric(
  'io_file_duration_seconds',
  'File I/O operation duration in seconds',
  IO_DURATION_BUCKETS,
);

export function recordHttpRequest(labels: Labels, durationSeconds: number): void {
  httpRequestsTotal.inc(labels);
  httpRequestDuration.observe(labels, durationSeconds);
}

export function recordFileOperation(
  operation: 'read' | 'write',
  bytes: number,
  durationSeconds: number,
): void {
  ioFileOperationsTotal.inc({ operation });
  ioFileBytesTotal.inc({ operation }, bytes);
  ioFileDuration.observe({ operation }, durationSeconds);
}

export function renderMetrics(): string {
  return [
    httpRequestsTotal.render(),
    httpRequestDuration.render(),
    ioFileOperationsTotal.render(),
    ioFileBytesTotal.render(),
    ioFileDuration.render(),
  ].join('\n');
}

function labelsKey(labels: Labels): string {
  return Object.entries(labels)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${String(value)}`)
    .join('|');
}

function renderLabels(labels: Labels): string {
  const entries = Object.entries(labels).sort(([left], [right]) => left.localeCompare(right));

  if (entries.length === 0) {
    return '';
  }

  return `{${entries
    .map(([key, value]) => `${key}="${escapeLabelValue(String(value))}"`)
    .join(',')}}`;
}

function escapeLabelValue(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
}
