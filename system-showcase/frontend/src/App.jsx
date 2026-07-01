import { startTransition, useEffect, useState } from 'react';

const AUTO_REFRESH_MS = 5000;

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

function fmtNumber(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'n/a';
  }

  const numeric = Number(value);
  if (unit === 'seconds') {
    if (numeric < 1) {
      return `${(numeric * 1000).toFixed(0)} ms`;
    }
    return `${numeric.toFixed(2)} s`;
  }
  if (unit === 'ratio') {
    return `${(numeric * 100).toFixed(2)}%`;
  }
  if (unit === 'count') {
    return new Intl.NumberFormat().format(Math.round(numeric));
  }
  if (unit === 'cores') {
    return `${numeric.toFixed(2)} cores`;
  }
  if (unit === 'rps') {
    return `${numeric.toFixed(2)} rps`;
  }
  if (unit === 'MB') {
    return `${numeric.toFixed(1)} MB`;
  }
  return numeric.toFixed(2);
}

function fmtJson(value) {
  if (value === null || value === undefined) {
    return 'Unavailable';
  }
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function toFieldRows(objectValue) {
  if (!objectValue || typeof objectValue !== 'object') {
    return [];
  }

  return Object.entries(objectValue).map(([key, value]) => ({
    key,
    value:
      typeof value === 'boolean'
        ? value
          ? 'true'
          : 'false'
        : Array.isArray(value)
          ? value.length
            ? value.join(', ')
            : '[]'
          : value === null || value === undefined || value === ''
            ? 'n/a'
            : String(value),
  }));
}

function sparklinePath(points, width, height) {
  if (!points.length) {
    return '';
  }

  const values = points.map((point) => Number(point.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  return points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((Number(point.value) - min) / range) * height;
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
}

function Section({ title, subtitle, children, accent = 'sand' }) {
  return (
    <section className={`panel panel-${accent}`}>
      <div className="panel-header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function MetricCard({ metric }) {
  return (
    <article className="metric-card">
      <div className="metric-meta">
        <span>{metric.title}</span>
        <small>{metric.description}</small>
      </div>
      <strong>{fmtNumber(metric.value, metric.unit)}</strong>
    </article>
  );
}

function ChartCard({ chart }) {
  const primarySeries = chart.series?.[0]?.points ?? [];
  const path = sparklinePath(primarySeries, 280, 92);
  return (
    <article className="chart-card">
      <div className="chart-topline">
        <div>
          <span>{chart.title}</span>
          <small>{chart.description}</small>
        </div>
        <strong>{fmtNumber(chart.currentValue, chart.unit)}</strong>
      </div>
      <svg viewBox="0 0 280 92" className="sparkline" aria-hidden="true">
        <defs>
          <linearGradient id={`fill-${chart.id}`} x1="0%" x2="0%" y1="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(201, 91, 55, 0.45)" />
            <stop offset="100%" stopColor="rgba(201, 91, 55, 0.02)" />
          </linearGradient>
        </defs>
        {path ? (
          <>
            <path
              d={`${path} L280,92 L0,92 Z`}
              fill={`url(#fill-${chart.id})`}
              stroke="none"
            />
            <path d={path} fill="none" stroke="#c95b37" strokeWidth="3" strokeLinecap="round" />
          </>
        ) : null}
      </svg>
      {chart.error ? <p className="chart-error">{chart.error}</p> : null}
      <code>{chart.query}</code>
    </article>
  );
}

function FieldGrid({ rows }) {
  if (!rows.length) {
    return <p className="muted">No values available yet.</p>;
  }

  return (
    <div className="field-grid">
      {rows.map((row) => (
        <div key={row.key} className="field-card">
          <span>{row.key}</span>
          <strong>{row.value}</strong>
        </div>
      ))}
    </div>
  );
}

function DataTable({ columns, rows, emptyMessage }) {
  if (!rows.length) {
    return <p className="muted">{emptyMessage}</p>;
  }

  return (
    <div className="table-shell">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.name || row.key || `${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{column.render ? column.render(row[column.key], row) : row[column.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonDetails({ title, value }) {
  return (
    <details className="json-details">
      <summary>{title}</summary>
      <pre>{fmtJson(value)}</pre>
    </details>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [requestError, setRequestError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const basePath = discoverBasePath();

  async function loadSnapshot(forceRefresh) {
    if (forceRefresh) {
      setRefreshing(true);
    }
    setRequestError('');

    try {
      const response = await fetch(
        `${basePath}/api/snapshot${forceRefresh ? '?forceRefresh=true' : ''}`,
      );
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

  useEffect(() => {
    void loadSnapshot(true);
  }, []);

  useEffect(() => {
    if (!autoRefresh) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void loadSnapshot(false);
    }, AUTO_REFRESH_MS);

    return () => window.clearInterval(timer);
  }, [autoRefresh]);

  const cards = snapshot?.system?.cards ?? [];
  const charts = snapshot?.system?.charts ?? [];
  const controller = snapshot?.controller ?? {};
  const resources = snapshot?.resources ?? {};
  const activeScaler = snapshot?.activeScaler;
  const scalerSpec = activeScaler?.spec ?? {};
  const scalerStatus = activeScaler?.status ?? {};
  const workerPrototypeSpec = scalerSpec.workerPrototype ?? {};
  const deployment = resources.deployment ?? {};
  const loadTest = snapshot?.loadTest ?? {};
  const errors = snapshot?.errors ?? [];

  return (
    <div className="app-shell">
      <div className="backdrop backdrop-one" />
      <div className="backdrop backdrop-two" />
      <main className="dashboard">
        <header className="hero">
          <div>
            <p className="eyebrow">Predictive autoscaling live view</p>
            <h1>System Showcase</h1>
            <p className="hero-copy">
              This dashboard merges Prometheus, CustomScaler status, and live Kubernetes
              resources into one refreshable control-room view.
            </p>
          </div>
          <div className="hero-actions">
            <button className="primary-button" type="button" onClick={() => void loadSnapshot(true)}>
              {refreshing ? 'Refreshing...' : 'Refresh now'}
            </button>
            <label className="toggle">
              <input
                checked={autoRefresh}
                onChange={(event) => setAutoRefresh(event.target.checked)}
                type="checkbox"
              />
              <span>Auto refresh every 5s</span>
            </label>
            <div className="timestamp-card">
              <span>Latest snapshot</span>
              <strong>{fmtTimestamp(snapshot?.generatedAt)}</strong>
            </div>
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

        <Section
          title="Overview"
          subtitle={
            activeScaler
              ? `${activeScaler.namespace}/${activeScaler.name} targeting ${activeScaler.spec?.deploymentName || 'n/a'}`
              : 'Waiting for a CustomScaler resource'
          }
          accent="terracotta"
        >
          <div className="metric-grid">
            {cards.map((metric) => (
              <MetricCard key={metric.id} metric={metric} />
            ))}
          </div>
        </Section>

        <Section
          title="System Signals"
          subtitle="Prometheus-backed time series pulled directly by the showcase backend."
          accent="olive"
        >
          <div className="chart-grid">
            {charts.map((chart) => (
              <ChartCard key={chart.id} chart={chart} />
            ))}
          </div>
        </Section>

        <div className="two-column">
          <Section
            title="Scaler Context"
            subtitle="The current spec and compact status on the selected CustomScaler."
            accent="slate"
          >
            <FieldGrid
              rows={toFieldRows({
                url: scalerSpec.url,
                deploymentName: scalerSpec.deploymentName,
                forecastDeployment: scalerSpec.forecastDeployment,
                intervalMinutes: scalerSpec.intervalMinutes,
                safetyFactor: scalerSpec.safetyFactor,
                sparePod: scalerSpec.sparePod,
                minReplicas: scalerSpec.minReplicas,
                maxReplicas: scalerSpec.maxReplicas,
                workerTargetCount: workerPrototypeSpec.targetWorkerCount,
                workerMaxBatchSize: workerPrototypeSpec.maxBatchSize,
                workerNodeLabelKey: workerPrototypeSpec.nodeLabelKey,
                workerNodeLabelValue: workerPrototypeSpec.nodeLabelValue,
                currentReplicas: scalerStatus.currentReplicas,
                lastDesiredReplicas: scalerStatus.lastDesiredReplicas,
                reactivePressureBump: scalerStatus.reactivePressureBump,
                reactivePressureReason: scalerStatus.reactivePressureReason,
              })}
            />
          </Section>

          <Section
            title="Controller Defaults"
            subtitle="Environment-backed scaler defaults currently visible on the controller manager deployment."
            accent="sand"
          >
            <FieldGrid rows={toFieldRows(controller.policyDefaults)} />
          </Section>
        </div>

        <div className="two-column">
          <Section
            title="Pod Reconciler"
            subtitle="Forecast request/response, replica math, and reactive pressure decision from the latest pod loop."
            accent="terracotta"
          >
            <FieldGrid
              rows={toFieldRows({
                observedAt: controller.podLoop?.observedAt,
                targetDeployment: controller.podLoop?.targetDeployment,
                forecastContractId: controller.podLoop?.forecastContractId,
                forecastModelName: controller.podLoop?.forecastModelName,
                forecastModelVersion: controller.podLoop?.forecastModelVersion,
                forecastRemoteContract: controller.podLoop?.forecastRemoteContract,
                forecastRemoteEndpoint: controller.podLoop?.forecastRemoteEndpoint,
                peakRequestsPerMinute: controller.podLoop?.peakRequestsPerMinute,
                peakCpuSecondsPerMinute: controller.podLoop?.peakCpuSecondsPerMinute,
                requestReplicaDemand: controller.podLoop?.requestReplicaDemand,
                cpuReplicaDemand: controller.podLoop?.cpuReplicaDemand,
                currentReplicas: controller.podLoop?.currentReplicas,
                proposedReplicas: controller.podLoop?.proposedReplicas,
                desiredReplicas: controller.podLoop?.desiredReplicas,
                currentReactivePressureBump: controller.podLoop?.currentReactivePressureBump,
                nextReactivePressureBump: controller.podLoop?.nextReactivePressureBump,
                reactivePressureReason: controller.podLoop?.reactivePressureReason,
                scaleDownAllowed: controller.podLoop?.scaleDownAllowed,
                scaleDownReason: controller.podLoop?.scaleDownReason,
                appliedScale: controller.podLoop?.appliedScale,
              })}
            />
            <JsonDetails title="Forecast request payload" value={controller.podLoop?.forecastRequestPayloadJson} />
            <JsonDetails title="Forecast response payload" value={controller.podLoop?.forecastResponseBodyJson} />
          </Section>

          <Section
            title="Node Reconciler"
            subtitle="Worker target computation and executor planning from the latest node loop."
            accent="olive"
          >
            <FieldGrid
              rows={toFieldRows({
                observedAt: controller.nodeLoop?.observedAt,
                targetDeployment: controller.nodeLoop?.targetDeployment,
                desiredReplicas: controller.nodeLoop?.desiredReplicas,
                workerTargetMode: controller.nodeLoop?.workerTargetMode,
                workerCapacityStrategy: controller.nodeLoop?.workerCapacityStrategy,
                targetWorkerCount: controller.nodeLoop?.targetWorkerCount,
                rawTargetWorkerCount: controller.nodeLoop?.rawTargetWorkerCount,
                unschedulablePods: controller.nodeLoop?.unschedulablePods,
                safetyPods: controller.nodeLoop?.safetyPods,
                desiredPodsForCapacity: controller.nodeLoop?.desiredPodsForCapacity,
                readyWorkerCount: controller.nodeLoop?.readyWorkerCount,
                currentAppScheduledPods: controller.nodeLoop?.currentAppScheduledPods,
                totalAppSlotCapacity: controller.nodeLoop?.totalAppSlotCapacity,
                missingAppSlots: controller.nodeLoop?.missingAppSlots,
                requiredReadyWorkers: controller.nodeLoop?.requiredReadyWorkers,
                observedReadyWorkers: controller.nodeLoop?.observedReadyWorkers,
                pendingCreateWorkers: controller.nodeLoop?.pendingCreateWorkers,
                pendingDeleteWorkers: controller.nodeLoop?.pendingDeleteWorkers,
                effectiveWorkers: controller.nodeLoop?.effectiveWorkers,
                workersToCreate: controller.nodeLoop?.workersToCreate,
                workersToDelete: controller.nodeLoop?.workersToDelete,
                lastAction: controller.nodeLoop?.lastAction,
                lastReason: controller.nodeLoop?.lastReason,
              })}
            />
            <JsonDetails title="Active worker operations" value={controller.nodeLoop?.activeOperations} />
          </Section>
        </div>

        <Section
          title="Cluster Reality"
          subtitle="What Kubernetes currently says about the deployment, pods, worker nodes, and worker jobs."
          accent="slate"
        >
          <div className="resource-group">
            <div>
              <h3>Deployment</h3>
              <FieldGrid
                rows={toFieldRows({
                  name: deployment.name,
                  namespace: deployment.namespace,
                  images: deployment.images,
                  desiredReplicas: deployment.desiredReplicas,
                  readyReplicas: deployment.readyReplicas,
                  availableReplicas: deployment.availableReplicas,
                  updatedReplicas: deployment.updatedReplicas,
                  observedGeneration: deployment.observedGeneration,
                })}
              />
              <JsonDetails title="Deployment conditions" value={deployment.conditions} />
            </div>
            <div>
              <h3>Pods</h3>
              <DataTable
                columns={[
                  { key: 'name', label: 'Pod' },
                  { key: 'phase', label: 'Phase' },
                  { key: 'ready', label: 'Ready', render: (value) => (value ? 'Ready' : 'Not ready') },
                  { key: 'nodeName', label: 'Node' },
                  { key: 'restartCount', label: 'Restarts' },
                ]}
                rows={resources.pods?.items || []}
                emptyMessage="No workload pods found for the selected deployment."
              />
            </div>
            <div>
              <h3>Managed worker nodes</h3>
              <DataTable
                columns={[
                  { key: 'name', label: 'Node' },
                  { key: 'ready', label: 'Ready', render: (value) => (value ? 'Ready' : 'Not ready') },
                  { key: 'roles', label: 'Roles', render: (value) => (value?.length ? value.join(', ') : 'worker') },
                  { key: 'allocatableCpu', label: 'CPU' },
                  { key: 'allocatableMemory', label: 'Memory' },
                ]}
                rows={resources.workerNodes?.items || []}
                emptyMessage="No managed worker nodes matched the current selector."
              />
            </div>
            <div>
              <h3>Worker jobs</h3>
              <DataTable
                columns={[
                  { key: 'name', label: 'Job' },
                  { key: 'operationType', label: 'Operation' },
                  { key: 'active', label: 'Active' },
                  { key: 'succeeded', label: 'Succeeded' },
                  { key: 'failed', label: 'Failed' },
                ]}
                rows={resources.jobs || []}
                emptyMessage="No worker executor jobs were found for the selected scaler."
              />
            </div>
          </div>
        </Section>

        <Section
          title="Load Test Placeholder"
          subtitle="The backend is already ready to accept one script payload and one metadata payload when we wire that flow in."
          accent="sand"
        >
          <div className="two-column-inline">
            <div className="subpanel">
              <h3>Injected script</h3>
              {loadTest.script ? (
                <>
                  <FieldGrid
                    rows={toFieldRows({
                      filename: loadTest.script.filename,
                      uploadedAt: loadTest.script.uploadedAt,
                      lineCount: loadTest.script.lineCount,
                    })}
                  />
                  <JsonDetails title="Script preview" value={loadTest.script.preview} />
                </>
              ) : (
                <p className="muted">No script has been injected yet.</p>
              )}
            </div>
            <div className="subpanel">
              <h3>Injected metadata</h3>
              {loadTest.metadata ? (
                <>
                  <FieldGrid
                    rows={toFieldRows({
                      uploadedAt: loadTest.metadata.uploadedAt,
                      metadataKeys: Object.keys(loadTest.metadata.payload || {}),
                    })}
                  />
                  <JsonDetails title="Metadata payload" value={loadTest.metadata.payload} />
                </>
              ) : (
                <p className="muted">No test metadata has been injected yet.</p>
              )}
            </div>
          </div>
        </Section>

        {loading && !snapshot ? <div className="loading">Loading the first system snapshot...</div> : null}
      </main>
    </div>
  );
}
