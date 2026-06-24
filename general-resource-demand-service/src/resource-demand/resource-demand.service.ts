import {
  Injectable,
  NotFoundException,
  OnModuleDestroy,
  OnModuleInit,
  ServiceUnavailableException,
} from '@nestjs/common';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import {
  PENDING_QUEUE_SIZE,
  SERVICE_NAME,
  WORKER_POOL_SIZE,
} from './resource-demand.constants';
import {
  loadRequestClassProfiles,
  sampleRequestClassDemand,
} from './resource-demand.profiles';
import {
  CompletedRequestClassExecution,
  RequestClassProfile,
  WorkerExecutionResult,
  WorkerResponse,
  WorkerTask,
} from './resource-demand.types';

@Injectable()
export class ResourceDemandService implements OnModuleInit, OnModuleDestroy {
  private readonly workerPath = join(__dirname, 'resource-demand.worker.js');
  private readonly poolSize = WORKER_POOL_SIZE;
  private readonly queueCapacity = PENDING_QUEUE_SIZE;
  private readonly workers: WorkerSlot[] = [];
  private readonly pendingQueue: PendingTask[] = [];
  private readonly requestClassProfiles = loadRequestClassProfiles();
  private nextTaskId = 1;
  private isShuttingDown = false;

  onModuleInit(): void {
    for (let index = 0; index < this.poolSize; index++) {
      this.workers.push(this.createWorkerSlot(index));
    }
  }

  onModuleDestroy(): void {
    this.isShuttingDown = true;

    while (this.pendingQueue.length > 0) {
      const pendingTask = this.pendingQueue.shift();

      pendingTask?.reject(
        new Error(`${SERVICE_NAME} worker queue is shutting down`),
      );
    }

    for (const slot of this.workers) {
      if (slot.activeTask) {
        slot.activeTask.pendingTask.reject(
          new Error(`${SERVICE_NAME} worker pool is shutting down`),
        );
        slot.activeTask = undefined;
      }

      void slot.worker.terminate();
    }
  }

  getRequestClasses(): string[] {
    return [...this.requestClassProfiles.keys()];
  }

  getRequestClassProfiles(): RequestClassProfile[] {
    return [...this.requestClassProfiles.values()];
  }

  async executeRequestClass(
    requestClass: string,
  ): Promise<CompletedRequestClassExecution> {
    const normalizedRequestClass = requestClass.trim().toLowerCase();
    const profile = this.requestClassProfiles.get(normalizedRequestClass);

    if (!profile) {
      throw new NotFoundException(
        `Unknown request class '${normalizedRequestClass}'`,
      );
    }

    const sampledDemand = sampleRequestClassDemand(profile);
    const wallClockStartNs = process.hrtime.bigint();
    const queueDepthOnArrival = this.pendingQueue.length;
    const workerSlot = this.findFreeWorker();

    if (!workerSlot && this.pendingQueue.length >= this.queueCapacity) {
      throw new ServiceUnavailableException(
        'No free worker thread or queue slot is available for this request class',
      );
    }

    return new Promise<CompletedRequestClassExecution>((resolve, reject) => {
      const pendingTask: PendingTask = {
        sampledDemand,
        wallClockStartNs,
        queueDepthOnArrival,
        resolve,
        reject,
      };

      if (workerSlot) {
        this.assignTaskToWorker(workerSlot, pendingTask);
        return;
      }

      this.pendingQueue.push(pendingTask);
    });
  }

  private createWorkerSlot(index: number): WorkerSlot {
    const slot: WorkerSlot = {
      id: index,
      worker: new Worker(this.workerPath),
      busy: false,
    };

    this.attachWorkerListeners(slot);
    return slot;
  }

  private assignTaskToWorker(slot: WorkerSlot, pendingTask: PendingTask): void {
    const taskId = this.nextTaskId++;
    const workerTask: WorkerTask = {
      taskId,
      requestClass: pendingTask.sampledDemand.requestClass,
      targetThreadCpuTimeNs: pendingTask.sampledDemand.targetThreadCpuTimeNs,
    };

    pendingTask.dispatchedAtNs = process.hrtime.bigint();
    slot.busy = true;
    slot.activeTask = { taskId, pendingTask };
    slot.worker.postMessage(workerTask);
  }

  private attachWorkerListeners(slot: WorkerSlot): void {
    slot.worker.on('message', (message: WorkerResponse) => {
      const activeTask = slot.activeTask;

      if (!activeTask || activeTask.taskId !== message.taskId) {
        return;
      }

      slot.busy = false;
      slot.activeTask = undefined;

      if (message.error) {
        activeTask.pendingTask.reject(new Error(message.error));
        this.dispatchNextPendingTask();
        return;
      }

      if (!message.result) {
        activeTask.pendingTask.reject(
          new Error(
            `Worker slot ${slot.id} returned no result for task ${message.taskId}`,
          ),
        );
        this.dispatchNextPendingTask();
        return;
      }

      activeTask.pendingTask.resolve(
        this.buildCompletedExecution(
          slot.id,
          activeTask.pendingTask,
          message.result,
        ),
      );
      this.dispatchNextPendingTask();
    });

    slot.worker.on('error', (error) => {
      this.handleWorkerFailure(slot, error);
    });

    slot.worker.on('exit', (code) => {
      if (code !== 0 && !this.isShuttingDown) {
        this.handleWorkerFailure(
          slot,
          new Error(`Worker slot ${slot.id} exited with code ${code}`),
        );
      }
    });
  }

  private handleWorkerFailure(slot: WorkerSlot, error: Error): void {
    if (this.isShuttingDown) {
      return;
    }

    if (slot.activeTask) {
      slot.activeTask.pendingTask.reject(error);
      slot.activeTask = undefined;
    }

    slot.busy = false;
    slot.worker.removeAllListeners();
    slot.worker = new Worker(this.workerPath);
    this.attachWorkerListeners(slot);
    this.dispatchNextPendingTask();
  }

  private buildCompletedExecution(
    workerId: number,
    pendingTask: PendingTask,
    workerResult: WorkerExecutionResult,
  ): CompletedRequestClassExecution {
    const responsePayload = buildResponsePayload(
      pendingTask.sampledDemand.requestClass,
      pendingTask.sampledDemand.targetResponsePayloadBytes,
    );
    const wallTimeMs =
      Number(process.hrtime.bigint() - pendingTask.wallClockStartNs) / 1e6;
    const queueWaitMs = pendingTask.dispatchedAtNs
      ? Number(pendingTask.dispatchedAtNs - pendingTask.wallClockStartNs) / 1e6
      : 0;

    return {
      requestClass: pendingTask.sampledDemand.requestClass,
      targetThreadCpuMs: pendingTask.sampledDemand.targetThreadCpuMs,
      observedThreadCpuMs: workerResult.observedThreadCpuTimeNs / 1e6,
      targetResponsePayloadBytes:
        pendingTask.sampledDemand.targetResponsePayloadBytes,
      actualResponsePayloadBytes: responsePayload.byteLength,
      appTimeMs: wallTimeMs,
      queueWaitMs,
      queueDepthOnArrival: pendingTask.queueDepthOnArrival,
      workerId,
      workerChecksum: workerResult.workerChecksum,
      responsePayload,
    };
  }

  private dispatchNextPendingTask(): void {
    if (this.isShuttingDown) {
      return;
    }

    const workerSlot = this.findFreeWorker();
    const pendingTask = this.pendingQueue.shift();

    if (!workerSlot || !pendingTask) {
      if (pendingTask) {
        this.pendingQueue.unshift(pendingTask);
      }
      return;
    }

    this.assignTaskToWorker(workerSlot, pendingTask);
  }

  private findFreeWorker(): WorkerSlot | undefined {
    return this.workers.find((slot) => !slot.busy);
  }
}

type ActiveTask = {
  taskId: number;
  pendingTask: PendingTask;
};

type WorkerSlot = {
  id: number;
  worker: Worker;
  busy: boolean;
  activeTask?: ActiveTask;
};

type PendingTask = {
  sampledDemand: {
    requestClass: string;
    targetThreadCpuMs: number;
    targetThreadCpuTimeNs: number;
    targetResponsePayloadBytes: number;
  };
  wallClockStartNs: bigint;
  dispatchedAtNs?: bigint;
  queueDepthOnArrival: number;
  resolve: (
    value:
      | CompletedRequestClassExecution
      | PromiseLike<CompletedRequestClassExecution>,
  ) => void;
  reject: (reason?: unknown) => void;
};

function buildResponsePayload(
  requestClass: string,
  targetResponsePayloadBytes: number,
): Buffer {
  const payload = Buffer.alloc(targetResponsePayloadBytes);
  const seed = Buffer.from(
    `${SERVICE_NAME}|${requestClass}|response-payload`,
    'utf8',
  );
  let offset = 0;

  while (offset < payload.length) {
    const copied = seed.copy(
      payload,
      offset,
      0,
      Math.min(seed.length, payload.length - offset),
    );
    offset += copied;
  }

  return payload;
}
