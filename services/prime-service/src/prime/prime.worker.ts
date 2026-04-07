import { parentPort } from 'node:worker_threads';
import { executePrimeTask, PrimeTask } from './prime.compute';

if (!parentPort) {
  throw new Error('Prime worker must run inside a worker thread');
}

const port = parentPort;

type WorkerRequest = {
  taskId: number;
  task: PrimeTask;
};

port.on('message', (message: WorkerRequest) => {
  try {
    const result = executePrimeTask(message.task);
    port.postMessage({ taskId: message.taskId, result });
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Unknown worker error';
    port.postMessage({ taskId: message.taskId, error: reason });
  }
});
