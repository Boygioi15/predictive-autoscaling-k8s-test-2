import {
  Injectable,
  Logger,
  OnModuleDestroy,
  OnModuleInit,
} from '@nestjs/common';
import { Worker } from 'node:worker_threads';
import { join } from 'node:path';
import { PrimeTask } from './prime.compute';

@Injectable()
export class PrimeService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(PrimeService.name);
  private readonly intervalSeconds = 1.5;
  private intervalRef?: NodeJS.Timeout;
  private readonly workerPath = join(__dirname, 'prime.worker.js');
  private readonly poolSize = 3;
  private readonly workers: WorkerSlot[] = [];
  private readonly pendingTasks: QueuedTask<unknown>[] = [];
  private nextTaskId = 1;
  private isShuttingDown = false;

  onModuleInit(): void {
    for (let index = 0; index < this.poolSize; index++) {
      this.workers.push(this.createWorkerSlot(index));
    }
  }

  onModuleDestroy(): void {
    this.isShuttingDown = true;

    if (this.intervalRef) {
      clearInterval(this.intervalRef);
    }

    while (this.pendingTasks.length > 0) {
      const task = this.pendingTasks.shift();
      task?.reject(new Error('Prime worker pool is shutting down'));
    }

    for (const slot of this.workers) {
      if (slot.activeTask) {
        slot.activeTask.reject(new Error('Prime worker pool is shutting down'));
        slot.activeTask = undefined;
      }

      void slot.worker.terminate();
    }
  }

  // onModuleInit(): void {
  //   const kthPrimeTarget = 200000;
  //   this.logger.log(
  //     `Starting prime background job every ${this.intervalSeconds}s for the ${kthPrimeTarget}th prime`,
  //   );
  //   this.runScheduledJob(kthPrimeTarget);
  //   this.intervalRef = setInterval(() => {
  //     this.runScheduledJob(kthPrimeTarget);
  //   }, this.intervalSeconds * 1000);
  // }

  private enqueueTask<T>(task: PrimeTask): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.pendingTasks.push({
        taskId: this.nextTaskId++,
        task,
        resolve,
        reject,
      });
      this.dispatchQueuedTasks();
    });
  }

  countPrimesInRange(n: number): Promise<number> {
    return this.enqueueTask<number>({ type: 'countPrimesInRange', value: n });
  }

  findKthPrime(k: number): Promise<number> {
    return this.enqueueTask<number>({ type: 'findKthPrime', value: k });
  }

  // private async runScheduledJob(k: number): Promise<void> {
  //   const start = Date.now();
  //   const result = await this.findKthPrime(k);
  //   const end = Date.now();

  //   this.logger.log(
  //     `Background job completed: ${k}th prime = ${result}, time taken = ${end - start}ms`,
  //   );
  // }

  checkIsPrime(n: number): Promise<{ isPrime: boolean; message: string }> {
    return this.enqueueTask<{ isPrime: boolean; message: string }>({
      type: 'checkIsPrime',
      value: n,
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

  private dispatchQueuedTasks(): void {
    while (this.pendingTasks.length > 0) {
      const idleWorker = this.workers.find((slot) => !slot.busy);

      if (!idleWorker) {
        return;
      }

      const nextTask = this.pendingTasks.shift();

      if (!nextTask) {
        return;
      }

      idleWorker.busy = true;
      idleWorker.activeTask = nextTask;
      idleWorker.worker.postMessage({
        taskId: nextTask.taskId,
        task: nextTask.task,
      });
    }
  }

  private handleWorkerFailure(slot: WorkerSlot, error: Error): void {
    if (this.isShuttingDown) {
      return;
    }

    if (slot.activeTask) {
      slot.activeTask.reject(error);
      slot.activeTask = undefined;
    }

    slot.busy = false;
    slot.worker.removeAllListeners();
    slot.worker = new Worker(this.workerPath);
    this.attachWorkerListeners(slot);
    this.dispatchQueuedTasks();
  }

  private attachWorkerListeners(slot: WorkerSlot): void {
    slot.worker.on('message', (message: WorkerResponse<unknown>) => {
      const activeTask = slot.activeTask;

      if (!activeTask || activeTask.taskId !== message.taskId) {
        this.logger.warn(
          `Received unexpected worker response on slot ${slot.id} for task ${message.taskId}`,
        );
        return;
      }

      slot.busy = false;
      slot.activeTask = undefined;

      if (message.error) {
        activeTask.reject(new Error(message.error));
      } else {
        activeTask.resolve(message.result);
      }

      this.dispatchQueuedTasks();
    });

    slot.worker.on('error', (replacementError) => {
      this.handleWorkerFailure(slot, replacementError);
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
}

type QueuedTask<T> = {
  taskId: number;
  task: PrimeTask;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
};

type WorkerResponse<T> = {
  taskId: number;
  result?: T;
  error?: string;
};

type WorkerSlot = {
  id: number;
  worker: Worker;
  busy: boolean;
  activeTask?: QueuedTask<unknown>;
};
