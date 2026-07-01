import { startTransition, useEffect, useState } from 'react';
import Chart from 'react-apexcharts';

const AUTO_REFRESH_MS = 5000;
const SIDEBAR_TABS = [
  { id: 'pod-config', label: 'Pod config' },
  { id: 'node-config', label: 'Node config' },
  { id: 'job-status', label: 'Job status' },
];
const EVENT_HISTORY_COLUMNS = 16;
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const LOOKBACK_POINTS = 60;
const FORECAST_POINTS = 20;
const POD_SIGNAL_ORDER = ['cpu', 'requests', 'network'];
const POD_LOG_KEYS = new Set([
  'currentReplicas',
  'proposedReplicas',
  'desiredReplicas',
  'requestReplicaDemand',
  'cpuReplicaDemand',
  'baseReplicaDemand',
  'dominantSignal',
  'currentReactivePressureBump',
  'nextReactivePressureBump',
  'reactivePressureReplicaBump',
  'reactivePressureReason',
  'scaleDownAllowed',
  'scaleDownReason',
  'appliedScale',
]);

function discoverBasePath() {
  const path = window.location.pathname || '/system-showcase/';
  if (path === '/') {
    return '/system-showcase';
  }
  return path.endsWith('/') ? path.slice(0, -1) : path;
}

function fmtTimestamp(value) {
  if (!value) {
    return 'Unavailable';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    month: 'short',
    day: 'numeric',
  }).format(date);
}

function fmtMinute(value) {
  if (!value) {
    return 'Unknown minute';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: 'numeric',
  }).format(date);
}

function fmtMinuteLabel(value) {
  if (!value) {
    return '--:--';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(11, 16) || value;
  }

  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function fmtLocalInputValue(value) {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function localInputToIso(value) {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  return date.toISOString();
}

function fmtNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'n/a';
  }
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function fmtMetricValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'n/a';
  }

  const numeric = Number(value);
  if (unit === 'bytes/min') {
    const absolute = Math.abs(numeric);
    if (absolute >= 1024 ** 3) {
      return `${(numeric / 1024 ** 3).toFixed(2)} GB/min`;
    }
    if (absolute >= 1024 ** 2) {
      return `${(numeric / 1024 ** 2).toFixed(2)} MB/min`;
    }
    if (absolute >= 1024) {
      return `${(numeric / 1024).toFixed(2)} KB/min`;
    }
    return `${numeric.toFixed(0)} B/min`;
  }
  if (unit === 'req/min') {
    return `${fmtNumber(numeric)} req/min`;
  }
  if (unit === 'sec/min') {
    return `${numeric.toFixed(2)} sec/min`;
  }
  return fmtNumber(numeric);
}

function fmtAxisValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '';
  }

  const numeric = Number(value);
  if (unit === 'bytes/min') {
    const absolute = Math.abs(numeric);
    if (absolute >= 1024 ** 3) {
      return `${(numeric / 1024 ** 3).toFixed(1)} GB`;
    }
    if (absolute >= 1024 ** 2) {
      return `${(numeric / 1024 ** 2).toFixed(1)} MB`;
    }
    if (absolute >= 1024) {
      return `${(numeric / 1024).toFixed(1)} KB`;
    }
    return `${numeric.toFixed(0)} B`;
  }
  if (unit === 'req/min') {
    return fmtNumber(numeric);
  }
  if (unit === 'sec/min') {
    return numeric.toFixed(1);
  }
  return fmtNumber(numeric);
}

function fmtLogValue(value) {
  if (value === null || value === undefined || value === '') {
    return 'n/a';
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(', ') : '[]';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function toFieldRows(objectValue) {
  if (!objectValue || typeof objectValue !== 'object') {
    return [];
  }

  return Object.entries(objectValue).map(([key, value]) => ({
    key,
    value: fmtLogValue(value),
  }));
}

function seriesStats(values) {
  if (!values.length) {
    return { min: null, max: null };
  }
  return {
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

function horizonValues(values, horizons = [1, 5, 10, 15, 20]) {
  return horizons.map((horizon) => ({
    horizon,
    value: horizon <= values.length ? values[horizon - 1] : null,
  }));
}

function buildXAxisCategories(historyCount, forecastCount) {
  const total = historyCount + forecastCount;
  const categories = Array.from({ length: total }, () => '');

  if (historyCount > 0) {
    categories[0] = `-${historyCount}`;
    if (historyCount >= 45) {
      categories[14] = '-45';
    }
    if (historyCount >= 30) {
      categories[29] = '-30';
    }
    if (historyCount >= 15) {
      categories[44] = '-15';
    }
    categories[historyCount - 1] = 'now';
  }

  if (forecastCount >= 1 && historyCount < total) {
    categories[historyCount] = '+1';
  }
  if (forecastCount >= 5 && historyCount + 4 < total) {
    categories[historyCount + 4] = '+5';
  }
  if (forecastCount >= 10 && historyCount + 9 < total) {
    categories[historyCount + 9] = '+10';
  }
  if (forecastCount >= 15 && historyCount + 14 < total) {
    categories[historyCount + 14] = '+15';
  }
  if (forecastCount >= 20 && historyCount + 19 < total) {
    categories[historyCount + 19] = '+20';
  }

  return categories;
}

function SignalForecastChart({ signal }) {
  const inputValues = Array.isArray(signal.input)
    ? signal.input
        .filter((value) => value !== null && value !== undefined)
        .map((value) => Number(value))
        .slice(-LOOKBACK_POINTS)
    : [];
  const predictionValues = Array.isArray(signal.prediction)
    ? signal.prediction
        .filter((value) => value !== null && value !== undefined)
        .map((value) => Number(value))
        .slice(0, FORECAST_POINTS)
    : [];
  const historyCount = inputValues.length;
  const forecastCount = predictionValues.length;
  const allValues = [...inputValues, ...predictionValues];
  const stats = seriesStats(allValues);
  const xAxisCategories = buildXAxisCategories(historyCount, forecastCount);
  const historySeries = [...inputValues, ...Array.from({ length: forecastCount }, () => null)];
  const forecastSeries = [
    ...Array.from({ length: Math.max(historyCount - 1, 0) }, () => null),
    ...(historyCount ? [inputValues[historyCount - 1]] : []),
    ...predictionValues,
  ];
  const chartConfig = {
    type: 'line',
    height: 300,
    series: [
      { name: 'Lookback', data: historySeries },
      { name: 'Forecast', data: forecastSeries },
    ],
    options: {
      chart: {
        id: `${signal.id}-forecast-chart`,
        toolbar: { show: false },
        zoom: { enabled: false },
        animations: { enabled: false },
      },
      stroke: {
        curve: 'smooth',
        lineCap: 'round',
        width: [4, 4],
      },
      colors: ['#334155', '#0f766e'],
      dataLabels: { enabled: false },
      markers: { size: 0, hover: { sizeOffset: 3 } },
      legend: {
        show: true,
        position: 'top',
        horizontalAlign: 'right',
        fontSize: '12px',
        labels: { colors: '#607080' },
      },
      tooltip: {
        theme: 'light',
        x: {
          formatter(_value, { dataPointIndex }) {
            if (dataPointIndex < historyCount) {
              return `Lookback step ${dataPointIndex + 1} of ${historyCount}`;
            }
            return `Forecast step ${dataPointIndex - historyCount + 1} of ${forecastCount}`;
          },
        },
        y: {
          formatter(value) {
            return fmtMetricValue(value, signal.unit);
          },
        },
      },
      grid: {
        show: true,
        borderColor: '#d8e0ea',
        strokeDashArray: 5,
        xaxis: { lines: { show: true } },
        yaxis: { lines: { show: true } },
        padding: { top: 8, right: 16, left: 8, bottom: 0 },
      },
      xaxis: {
        categories: xAxisCategories,
        axisTicks: { show: false },
        axisBorder: { show: false },
        tickPlacement: 'on',
        labels: {
          style: {
            colors: '#607080',
            fontSize: '12px',
            fontFamily: 'inherit',
            fontWeight: 400,
          },
        },
      },
      yaxis: {
        min: stats.min === null ? undefined : Math.max(0, stats.min * 0.9),
        max: stats.max === null ? undefined : stats.max * 1.05,
        labels: {
          formatter(value) {
            return fmtAxisValue(value, signal.unit);
          },
          style: {
            colors: '#607080',
            fontSize: '12px',
            fontFamily: 'inherit',
            fontWeight: 400,
          },
        },
      },
      annotations: {
        xaxis: historyCount
          ? [
              {
                x: 'now',
                borderColor: '#94a3b8',
                strokeDashArray: 0,
              },
            ]
          : [],
      },
    },
  };

  return (
    <div className="forecast-chart-shell">
      <div className="forecast-chart-frame">
        {allValues.length ? (
          <Chart {...chartConfig} />
        ) : (
          <span className="mini-chart-empty">No data</span>
        )}
      </div>
      <div className="forecast-chart-summary">
        <div className="forecast-chart-range">
          <span>Min {fmtMetricValue(stats.min, signal.unit)}</span>
          <span>Max {fmtMetricValue(stats.max, signal.unit)}</span>
          <span>Lookback {historyCount}</span>
          <span>Forecast {forecastCount}</span>
        </div>
      </div>
    </div>
  );
}

function SignalComparisonRow({ signal }) {
  return (
    <div className="signal-row signal-chart-row">
      <div className="signal-meta signal-meta-chart">
        <strong>{signal.label}</strong>
        <span>Current {fmtMetricValue(signal.inputLast, signal.unit)}</span>
        <span>Peak forecast {fmtMetricValue(signal.predictionPeak, signal.unit)}</span>
      </div>
      <div className="signal-chart-caption">
        <span>Lookback</span>
        <span className="signal-chart-caption-divider" />
        <span>Forecast</span>
      </div>
      <SignalForecastChart signal={signal} />
    </div>
  );
}

function LogList({ fields }) {
  if (!fields?.length) {
    return <p className="empty-copy">No log fields captured.</p>;
  }

  return (
    <div className="log-list">
      {fields.map((field) => (
        <div key={field.key} className="log-row">
          <span>{field.label}</span>
          <strong>{fmtLogValue(field.value)}</strong>
        </div>
      ))}
    </div>
  );
}

function filterLogFields(fields, allowedKeys) {
  return (fields || []).filter((field) => allowedKeys.has(field.key));
}

function hasPodScaleEvent(loop) {
  return Boolean(loop?.appliedScale);
}

function hasNodeScaleEvent(loop) {
  return Number(loop?.workersToCreate || 0) > 0 || Number(loop?.workersToDelete || 0) > 0;
}

function buildPodEventSummary(group) {
  const loops = group.podLoops || [];
  const activeLoops = loops.filter(hasPodScaleEvent);
  if (!activeLoops.length) {
    return `Pod reconciler did not scale at ${fmtMinute(group.minuteBucket)}.`;
  }

  const latest = activeLoops[activeLoops.length - 1];
  const current = fmtLogValue(latest.currentReplicas);
  const desired = fmtLogValue(latest.desiredReplicas);
  const signal = fmtLogValue(latest.dominantSignal);
  const reason = latest.reactivePressureReason
    ? ` Reactive reason: ${fmtLogValue(latest.reactivePressureReason)}.`
    : '';
  const countPrefix =
    activeLoops.length > 1 ? `${activeLoops.length} pod scale events. ` : '1 pod scale event. ';

  return `${countPrefix}${fmtMinute(group.minuteBucket)} latest pod scale ${current} -> ${desired} replicas. Dominant signal: ${signal}.${reason}`;
}

function buildNodeEventSummary(group) {
  const loops = group.nodeLoops || [];
  const activeLoops = loops.filter(hasNodeScaleEvent);
  if (!activeLoops.length) {
    return `Node reconciler did not scale at ${fmtMinute(group.minuteBucket)}.`;
  }

  const latest = activeLoops[activeLoops.length - 1];
  const createCount = Number(latest.workersToCreate || 0);
  const deleteCount = Number(latest.workersToDelete || 0);
  const actionParts = [];
  if (createCount > 0) {
    actionParts.push(`create ${createCount} worker${createCount === 1 ? '' : 's'}`);
  }
  if (deleteCount > 0) {
    actionParts.push(`delete ${deleteCount} worker${deleteCount === 1 ? '' : 's'}`);
  }
  const actionSummary = actionParts.join(', ');
  const reason = latest.lastReason ? ` Reason: ${fmtLogValue(latest.lastReason)}.` : '';
  const countPrefix =
    activeLoops.length > 1 ? `${activeLoops.length} node scale events. ` : '1 node scale event. ';

  return `${countPrefix}${fmtMinute(group.minuteBucket)} latest node action: ${actionSummary}. Target workers: ${fmtLogValue(latest.targetWorkerCount)}.${reason}`;
}

function EventHistoryTable({ minuteGroups, historySize }) {
  const recentGroups = [...minuteGroups.slice(0, EVENT_HISTORY_COLUMNS)].reverse();

  return (
    <section className="event-history-card">
      <div className="event-history-header">
        <strong>History size: {historySize}</strong>
        <span>Grouped by minute</span>
      </div>
      {recentGroups.length ? (
        <div className="event-history-grid">
          <div className="event-history-legend">
            <span>Pod</span>
            <span>Node</span>
          </div>
          {recentGroups.map((group) => {
            const podEventSummary = buildPodEventSummary(group);
            const nodeEventSummary = buildNodeEventSummary(group);
            const hasPodEvent = (group.podLoops || []).some(hasPodScaleEvent);
            const hasNodeEvent = (group.nodeLoops || []).some(hasNodeScaleEvent);

            return (
              <div key={group.groupKey} className="event-history-column">
                <span className="event-history-label">{fmtMinuteLabel(group.minuteBucket)}</span>
                <div className="event-history-pair">
                  <span
                    className={`event-dot${hasPodEvent ? ' active' : ''}`}
                    title={podEventSummary}
                    aria-label={podEventSummary}
                  />
                  <span
                    className={`event-dot${hasNodeEvent ? ' active' : ''}`}
                    title={nodeEventSummary}
                    aria-label={nodeEventSummary}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="empty-copy">No grouped minute history yet.</p>
      )}
    </section>
  );
}

function ScriptRangeChart({ rangeData }) {
  const series = (rangeData?.series || []).map((point) => ({
    x: new Date(point.realTime).getTime(),
    y: Number(point.requests || 0),
  }));
  const peakValue = rangeData?.summary?.peakRequestsPerSecond ?? 0;
  const nowTimestamp = Date.now();
  const rangeStart = series[0]?.x ?? null;
  const rangeEnd = series[series.length - 1]?.x ?? null;
  const showNowMarker =
    rangeStart !== null && rangeEnd !== null && nowTimestamp >= rangeStart && nowTimestamp <= rangeEnd;

  const chartConfig = {
    type: 'line',
    height: 300,
    series: [{ name: 'Requests/sec', data: series }],
    options: {
      chart: {
        id: 'script-range-chart',
        toolbar: { show: false },
        zoom: { enabled: false },
        animations: { enabled: false },
      },
      stroke: {
        curve: 'smooth',
        lineCap: 'round',
        width: 4,
      },
      colors: ['#2563eb'],
      dataLabels: { enabled: false },
      markers: { size: 0, hover: { sizeOffset: 3 } },
      legend: { show: false },
      tooltip: {
        theme: 'light',
        x: { format: 'dd MMM HH:mm' },
        y: {
          formatter(value) {
            return `${fmtNumber(value)} req/s`;
          },
        },
      },
      grid: {
        show: true,
        borderColor: '#d8e0ea',
        strokeDashArray: 5,
        xaxis: { lines: { show: true } },
        yaxis: { lines: { show: true } },
        padding: { top: 8, right: 16, left: 8, bottom: 0 },
      },
      xaxis: {
        type: 'datetime',
        axisTicks: { show: false },
        axisBorder: { show: false },
        labels: {
          datetimeUTC: false,
          style: {
            colors: '#607080',
            fontSize: '12px',
            fontFamily: 'inherit',
            fontWeight: 400,
          },
        },
      },
      yaxis: {
        min: 0,
        max: peakValue ? peakValue * 1.05 : undefined,
        labels: {
          formatter(value) {
            return fmtNumber(value);
          },
          style: {
            colors: '#607080',
            fontSize: '12px',
            fontFamily: 'inherit',
            fontWeight: 400,
          },
        },
      },
      annotations: {
        xaxis: showNowMarker
          ? [
              {
                x: nowTimestamp,
                borderColor: '#dc2626',
                strokeDashArray: 0,
                label: {
                  text: 'Now',
                  orientation: 'horizontal',
                  offsetY: -8,
                  style: {
                    background: '#dc2626',
                    color: '#ffffff',
                    fontSize: '11px',
                    fontWeight: 700,
                  },
                },
              },
            ]
          : [],
      },
    },
  };

  return (
    <div className="forecast-chart-shell">
      <div className="forecast-chart-frame">
        {series.length ? <Chart {...chartConfig} /> : <span className="mini-chart-empty">No data</span>}
      </div>
    </div>
  );
}

function WorkflowLoopCard({ podLoop, nodeLoop, minuteBucket }) {
  const orderedSignals = [...(podLoop?.signals || [])].sort(
    (left, right) => POD_SIGNAL_ORDER.indexOf(left.id) - POD_SIGNAL_ORDER.indexOf(right.id),
  );
  const podLogFields = filterLogFields(podLoop?.logFields, POD_LOG_KEYS);
  const nodeLogFields = nodeLoop?.logFields || [];
  const observedAt = podLoop?.observedAt || nodeLoop?.observedAt || minuteBucket;

  return (
    <article className="loop-entry workflow-loop-entry">
      <div className="workflow-timestamp">
        <h3>{fmtTimestamp(observedAt)}</h3>
      </div>

      <section className="prediction-panel">
        <div className="prediction-panel-header">
          <strong>AI model prediction</strong>
          <span>{podLoop?.forecastModelName || 'Unknown model'}</span>
        </div>
        {orderedSignals.length ? (
          <div className="signal-stack">
            {orderedSignals.map((signal) => (
              <SignalComparisonRow key={signal.id} signal={signal} />
            ))}
          </div>
        ) : (
          <div className="empty-panel">No AI prediction details were captured for this loop.</div>
        )}
      </section>

      <div className="workflow-log-grid">
        <div className="log-panel">
          <div className="log-panel-header">
            <strong>Pod reconciler loop log</strong>
          </div>
          {podLoop ? <LogList fields={podLogFields} /> : <p className="empty-copy">No pod loop recorded.</p>}
        </div>

        <div className="log-panel">
          <div className="log-panel-header">
            <strong>Node reconciler loop log</strong>
          </div>
          {nodeLoop ? <LogList fields={nodeLogFields} /> : <p className="empty-copy">No node loop recorded.</p>}
        </div>
      </div>
    </article>
  );
}

function FieldGrid({ title, rows }) {
  return (
    <section className="sidebar-section">
      <h3>{title}</h3>
      {rows.length ? (
        <div className="field-grid">
          {rows.map((row) => (
            <div key={row.key} className="field-card">
              <span>{row.key}</span>
              <strong>{row.value}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-copy">No values available.</p>
      )}
    </section>
  );
}

function JobStatusList({ jobs }) {
  if (!jobs.length) {
    return <p className="empty-copy">No worker jobs are currently tracked.</p>;
  }

  return (
    <div className="job-list">
      {jobs.map((job) => (
        <article key={job.name} className="job-card">
          <div className="job-card-header">
            <div>
              <h3>{job.name}</h3>
              <p>{job.operationType || 'worker job'}</p>
            </div>
            <span className="chip chip-default">{job.namespace}</span>
          </div>
          <div className="job-stats">
            <span>Active {fmtLogValue(job.active)}</span>
            <span>Succeeded {fmtLogValue(job.succeeded)}</span>
            <span>Failed {fmtLogValue(job.failed)}</span>
          </div>
          <div className="job-times">
            <small>Started {fmtTimestamp(job.startTime)}</small>
            <small>Completed {fmtTimestamp(job.completionTime)}</small>
          </div>
          {job.conditions?.length ? (
            <div className="job-conditions">
              {job.conditions.map((condition, index) => (
                <div key={`${condition.type}-${index}`} className="condition-row">
                  <strong>{condition.type}</strong>
                  <span>{condition.status}</span>
                  <small>{condition.reason || condition.message || 'No details'}</small>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [requestError, setRequestError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarTab, setSidebarTab] = useState('pod-config');
  const [expandedGroups, setExpandedGroups] = useState(() => new Set());
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [scriptRange, setScriptRange] = useState(null);
  const [scriptRangeLoading, setScriptRangeLoading] = useState(true);
  const [scriptRangeError, setScriptRangeError] = useState('');
  const [scriptRealStartInput, setScriptRealStartInput] = useState('');
  const [scriptWorldCupStartInput, setScriptWorldCupStartInput] = useState('');
  const [scriptDurationSecondsInput, setScriptDurationSecondsInput] = useState('3600');
  const basePath = discoverBasePath();

  async function loadSnapshot(forceRefresh) {
    if (forceRefresh) {
      setRefreshing(true);
    }
    setRequestError('');

    try {
      const params = new URLSearchParams();
      params.set('page', String(currentPage));
      params.set('pageSize', String(pageSize));
      if (forceRefresh) {
        params.set('forceRefresh', 'true');
      }

      const response = await fetch(`${basePath}/api/snapshot?${params.toString()}`);
      if (!response.ok) {
        throw new Error(`Snapshot request failed with status ${response.status}`);
      }
      const payload = await response.json();
      startTransition(() => {
        setSnapshot(payload);
      });
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : 'Unknown snapshot error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadScriptRange(useCurrentInputs = true) {
    setScriptRangeLoading(true);
    setScriptRangeError('');

    try {
      const params = new URLSearchParams();
      if (useCurrentInputs) {
        const realStartIso = localInputToIso(scriptRealStartInput);
        const worldCupStartIso = localInputToIso(scriptWorldCupStartInput);
        const durationSeconds = Number(scriptDurationSecondsInput);

        if (realStartIso) {
          params.set('realStart', realStartIso);
        }
        if (worldCupStartIso) {
          params.set('worldCupStart', worldCupStartIso);
        }
        if (durationSeconds > 0) {
          params.set('durationSeconds', String(Math.round(durationSeconds)));
        }
      }

      const queryString = params.toString();
      const response = await fetch(
        `${basePath}/api/script-range${queryString ? `?${queryString}` : ''}`,
      );
      if (!response.ok) {
        throw new Error(`Script range request failed with status ${response.status}`);
      }

      const payload = await response.json();
      startTransition(() => {
        setScriptRange(payload);
      });

      if (payload?.available && payload.query) {
        setScriptRealStartInput(fmtLocalInputValue(payload.query.realStart));
        setScriptWorldCupStartInput(fmtLocalInputValue(payload.query.worldCupStart));
        setScriptDurationSecondsInput(String(payload.query.durationSeconds || 3600));
      }
      if (!payload?.available && payload?.message) {
        setScriptRangeError(payload.message);
      }
    } catch (error) {
      setScriptRangeError(error instanceof Error ? error.message : 'Unknown script range error');
    } finally {
      setScriptRangeLoading(false);
    }
  }

  useEffect(() => {
    setExpandedGroups(new Set());
    void loadSnapshot(true);
  }, [currentPage, pageSize]);

  useEffect(() => {
    void loadScriptRange(false);
  }, []);

  useEffect(() => {
    if (!autoRefresh) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void loadSnapshot(false);
    }, AUTO_REFRESH_MS);

    return () => window.clearInterval(timer);
  }, [autoRefresh, currentPage, pageSize]);

  const activeScaler = snapshot?.activeScaler;
  const controller = snapshot?.controller ?? {};
  const sidebar = controller.sidebar ?? {};
  const minuteGroups = controller.minuteGroups ?? [];
  const recentMinuteGroups = controller.recentMinuteGroups ?? minuteGroups;
  const historyCounts = controller.historyCounts ?? {};
  const pagination = controller.pagination ?? {
    page: currentPage,
    pageSize,
    totalItems: minuteGroups.length,
    totalPages: 1,
    hasPreviousPage: false,
    hasNextPage: false,
    startItem: minuteGroups.length ? 1 : 0,
    endItem: minuteGroups.length,
  };
  const totalMinuteGroups = pagination.totalItems ?? historyCounts.minuteGroups ?? minuteGroups.length;
  const jobs = sidebar.jobStatus ?? [];
  const errors = snapshot?.errors ?? [];

  useEffect(() => {
    const serverPage = Number(pagination.page || 1);
    if (serverPage !== currentPage) {
      setCurrentPage(serverPage);
    }
  }, [currentPage, pagination.page]);

  function toggleGroup(groupKey) {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(groupKey)) {
        next.delete(groupKey);
      } else {
        next.add(groupKey);
      }
      return next;
    });
  }

  function renderSidebarBody() {
    if (sidebarTab === 'pod-config') {
      return (
        <>
          <FieldGrid title="CustomScaler pod spec" rows={toFieldRows(sidebar.podConfig?.spec)} />
          <FieldGrid title="Pod status" rows={toFieldRows(sidebar.podConfig?.status)} />
          <FieldGrid title="Pod defaults" rows={toFieldRows(sidebar.podConfig?.defaults)} />
        </>
      );
    }

    if (sidebarTab === 'node-config') {
      return (
        <>
          <FieldGrid title="Worker prototype spec" rows={toFieldRows(sidebar.nodeConfig?.spec)} />
          <FieldGrid title="Worker status" rows={toFieldRows(sidebar.nodeConfig?.status)} />
          <FieldGrid title="Node defaults" rows={toFieldRows(sidebar.nodeConfig?.defaults)} />
        </>
      );
    }

    return <JobStatusList jobs={jobs} />;
  }

  return (
    <div className={`workflow-app${sidebarOpen ? ' sidebar-open' : ''}`}>
      <header className="page-header">
        <div className="page-header-copy">
          <p className="eyebrow">Controller workflow only</p>
          <h1>Custom Operator Showcase</h1>
          <p>
            Minute-grouped pod and node reconciler history, with expandable loop details and a
            compact operator reference sidebar.
          </p>
          <EventHistoryTable minuteGroups={recentMinuteGroups} historySize={totalMinuteGroups} />
        </div>
        <div className="page-header-actions">
          <div className="summary-card">
            <span>Active scaler</span>
            <strong>
              {activeScaler ? `${activeScaler.namespace}/${activeScaler.name}` : 'No scaler selected'}
            </strong>
          </div>
          <div className="summary-card">
            <span>Latest snapshot</span>
            <strong>{fmtTimestamp(snapshot?.generatedAt)}</strong>
          </div>
          <button className="primary-button" type="button" onClick={() => void loadSnapshot(true)}>
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <button
            className="secondary-button"
            type="button"
            onClick={() => setSidebarOpen((value) => !value)}
          >
            {sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
          </button>
          <label className="toggle">
            <input
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
              type="checkbox"
            />
            <span>Auto refresh</span>
          </label>
        </div>
      </header>

      {requestError ? <div className="alert alert-error">{requestError}</div> : null}
      {errors.length ? (
        <div className="alert alert-warning">
          <strong>Partial data warnings:</strong>
          <ul>
            {errors.map((error, index) => (
              <li key={`${error.source}-${index}`}>
                <code>{error.source}</code> {error.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <section className="script-range-card">
        <div className="script-range-header">
          <div>
            <p className="eyebrow eyebrow-dark">Test Script Range</p>
            <h2>Replay window preview</h2>
            <p>
              Slice the full replay CSV by real start, World Cup 1998 start, and duration, then
              preview the request shape before you run it.
            </p>
          </div>
          <div className="script-range-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void loadScriptRange(true)}
              disabled={scriptRangeLoading}
            >
              {scriptRangeLoading ? 'Loading...' : 'Update range'}
            </button>
          </div>
        </div>

        <div className="script-range-controls">
          <label className="script-range-field">
            <span>Script start - real</span>
            <input
              type="datetime-local"
              value={scriptRealStartInput}
              onChange={(event) => setScriptRealStartInput(event.target.value)}
            />
          </label>

          <label className="script-range-field">
            <span>Script start - WC1998</span>
            <input
              type="datetime-local"
              value={scriptWorldCupStartInput}
              onChange={(event) => setScriptWorldCupStartInput(event.target.value)}
            />
          </label>

          <label className="script-range-field">
            <span>Duration (seconds)</span>
            <input
              type="number"
              min="1"
              step="1"
              value={scriptDurationSecondsInput}
              onChange={(event) => setScriptDurationSecondsInput(event.target.value)}
            />
          </label>
        </div>

        {scriptRangeError ? <div className="alert alert-error">{scriptRangeError}</div> : null}

        {scriptRange?.available ? (
          <div className="script-range-body">
            <div className="script-range-summary">
              <span>CSV {scriptRange.csvPath}</span>
              <strong>
                {fmtNumber(scriptRange.summary?.sampledPoints)} sampled points from{' '}
                {fmtNumber(scriptRange.summary?.totalPoints)} seconds
              </strong>
              <span>
                Real start {fmtTimestamp(scriptRange.query?.realStart)} | WC1998 start{' '}
                {fmtTimestamp(scriptRange.query?.worldCupStart)}
              </span>
              <span>
                Peak {fmtNumber(scriptRange.summary?.peakRequestsPerSecond)} req/s | Total{' '}
                {fmtNumber(scriptRange.summary?.totalRequests)} requests
              </span>
            </div>

            <ScriptRangeChart rangeData={scriptRange} />
          </div>
        ) : scriptRangeLoading ? (
          <div className="loading">Loading script range preview...</div>
        ) : (
          <div className="empty-panel">Script range preview is unavailable.</div>
        )}
      </section>

      <div className="workspace">
        <main className="timeline-shell">
          <div className="stats-row">
            <div className="stat-card">
              <span>Pod loop records</span>
              <strong>{fmtNumber(historyCounts.podLoops)}</strong>
            </div>
            <div className="stat-card">
              <span>Node loop records</span>
              <strong>{fmtNumber(historyCounts.nodeLoops)}</strong>
            </div>
            <div className="stat-card">
              <span>Minute groups</span>
              <strong>{fmtNumber(totalMinuteGroups)}</strong>
            </div>
            <div className="stat-card">
              <span>Tracked jobs</span>
              <strong>{fmtNumber(jobs.length)}</strong>
            </div>
          </div>

          <div className="pagination-toolbar">
            <div className="pagination-summary">
              <strong>
                Showing {fmtNumber(pagination.startItem)}-{fmtNumber(pagination.endItem)}
              </strong>
              <span>of {fmtNumber(totalMinuteGroups)} minute groups</span>
            </div>

            <label className="pagination-size">
              <span>Page size</span>
              <select
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value));
                  setCurrentPage(1);
                }}
              >
                {PAGE_SIZE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>

            <div className="pagination-actions">
              <span className="pagination-page-indicator">
                Page {fmtNumber(pagination.page)} / {fmtNumber(pagination.totalPages)}
              </span>
              <button
                className="secondary-button"
                type="button"
                disabled={!pagination.hasPreviousPage}
                onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
              >
                Newer
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={!pagination.hasNextPage}
                onClick={() => setCurrentPage((page) => page + 1)}
              >
                Older
              </button>
            </div>
          </div>

          <div className="timeline-list">
            {minuteGroups.length ? (
              minuteGroups.map((group) => {
                const isOpen = expandedGroups.has(group.groupKey);
                const podCount = group.podLoops?.length || 0;
                const nodeCount = group.nodeLoops?.length || 0;
                const workflowCount = Math.max(podCount, nodeCount);

                return (
                  <section key={group.groupKey} className={`minute-group${isOpen ? ' open' : ''}`}>
                    <button
                      className="minute-group-header"
                      type="button"
                      onClick={() => toggleGroup(group.groupKey)}
                    >
                      <div>
                        <h2>{fmtMinute(group.minuteBucket)}</h2>
                        <p>
                          {podCount} pod loop{podCount === 1 ? '' : 's'} | {nodeCount} node loop
                          {nodeCount === 1 ? '' : 's'}
                        </p>
                      </div>
                      <span className="expand-label">{isOpen ? 'Collapse' : 'Expand'}</span>
                    </button>

                    {isOpen ? (
                      <div className="minute-group-body">
                        {workflowCount ? (
                          Array.from({ length: workflowCount }, (_, index) => {
                            const podLoop = group.podLoops?.[index] || null;
                            const nodeLoop = group.nodeLoops?.[index] || null;
                            const loopKey = [
                              group.groupKey,
                              podLoop?.loopKey || 'no-pod',
                              nodeLoop?.loopKey || 'no-node',
                            ].join(':');

                            return (
                              <WorkflowLoopCard
                                key={loopKey}
                                minuteBucket={group.minuteBucket}
                                nodeLoop={nodeLoop}
                                podLoop={podLoop}
                              />
                            );
                          })
                        ) : (
                          <div className="empty-panel">No controller loop was recorded in this minute.</div>
                        )}
                      </div>
                    ) : null}
                  </section>
                );
              })
            ) : (
              <div className="empty-panel">No controller history has been captured yet.</div>
            )}
          </div>

          {loading && !snapshot ? <div className="loading">Loading controller workflow...</div> : null}
        </main>

        <aside className={`sidebar${sidebarOpen ? ' open' : ' closed'}`}>
          <div className="sidebar-header">
            <div>
              <p className="eyebrow eyebrow-dark">Reference sidebar</p>
              <h2>Operator context</h2>
            </div>
            <button className="icon-button" type="button" onClick={() => setSidebarOpen(false)}>
              Close
            </button>
          </div>

          <div className="sidebar-tabs">
            {SIDEBAR_TABS.map((tab) => (
              <button
                key={tab.id}
                className={`sidebar-tab${sidebarTab === tab.id ? ' active' : ''}`}
                type="button"
                onClick={() => setSidebarTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="sidebar-body">{renderSidebarBody()}</div>
        </aside>
      </div>
    </div>
  );
}
