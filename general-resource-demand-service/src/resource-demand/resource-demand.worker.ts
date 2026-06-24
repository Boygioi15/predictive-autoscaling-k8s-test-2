import { readFileSync } from 'node:fs';
import { parentPort } from 'node:worker_threads';
import { WorkerExecutionResult, WorkerTask } from './resource-demand.types';

if (!parentPort) {
  throw new Error('Resource demand worker must run inside a worker thread');
}

const port = parentPort;

port.on('message', (message: WorkerTask) => {
  try {
    const result = executeThreadCpuDemand(
      message.requestClass,
      BigInt(message.targetThreadCpuTimeNs),
    );
    port.postMessage({ taskId: message.taskId, result });
  } catch (error) {
    const reason =
      error instanceof Error ? error.message : 'Unknown worker error';
    port.postMessage({ taskId: message.taskId, error: reason });
  }
});

function executeThreadCpuDemand(
  requestClass: string,
  targetThreadCpuTimeNs: bigint,
): WorkerExecutionResult {
  const cpuStart = readThreadCpuTimeNs();
  let observedThreadCpuTimeNs = 0n;
  let workerChecksum = 0;

  while (observedThreadCpuTimeNs < targetThreadCpuTimeNs) {
    workerChecksum = burnCpuChunk(workerChecksum);
    observedThreadCpuTimeNs = readThreadCpuTimeNs() - cpuStart;
  }

  return {
    requestClass,
    observedThreadCpuTimeNs: Number(observedThreadCpuTimeNs),
    workerChecksum: workerChecksum >>> 0,
  };
}

function readThreadCpuTimeNs(): bigint {
  const [runtimeNs] = readFileSync('/proc/thread-self/schedstat', 'utf8')
    .trim()
    .split(/\s+/, 1);

  return BigInt(runtimeNs);
}

function burnCpuChunk(seed: number): number {
  let value = seed | 0;

  for (let index = 0; index < 20_000; index++) {
    value = Math.imul(value ^ index, 2246822519);
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
  }

  return value >>> 0;
}
