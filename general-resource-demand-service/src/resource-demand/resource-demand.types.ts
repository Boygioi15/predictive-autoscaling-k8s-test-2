export type CpuDemandProfile = {
  requestClass: string;
  baseThreadCpuMs: number;
  cpuWeight: number;
  cpuNoiseLimitMs: number;
};

export type CpuDemandConfig = {
  baseThreadCpuMs: number;
  cpuNoiseLimitMs: number;
  requestClassWeights: Record<string, number>;
};

export type ResponsePayloadPercentileProfile = {
  requestClass: string;
  p01Bytes: number;
  p05Bytes: number;
  p10Bytes: number;
  p25Bytes: number;
  p50Bytes: number;
  p75Bytes: number;
  p90Bytes: number;
  p95Bytes: number;
  p99Bytes: number;
};

export type RequestClassProfile = {
  requestClass: string;
  cpuDemandProfile: CpuDemandProfile;
  responsePayloadDemandProfile: ResponsePayloadPercentileProfile;
};

export type SampledRequestClassDemand = {
  requestClass: string;
  targetThreadCpuMs: number;
  targetThreadCpuTimeNs: number;
  targetResponsePayloadBytes: number;
};

export type WorkerTask = {
  taskId: number;
  requestClass: string;
  targetThreadCpuTimeNs: number;
};

export type WorkerExecutionResult = {
  requestClass: string;
  observedThreadCpuTimeNs: number;
  workerChecksum: number;
};

export type WorkerResponse = {
  taskId: number;
  result?: WorkerExecutionResult;
  error?: string;
};

export type CompletedRequestClassExecution = {
  requestClass: string;
  targetThreadCpuMs: number;
  observedThreadCpuMs: number;
  targetResponsePayloadBytes: number;
  actualResponsePayloadBytes: number;
  appTimeMs: number;
  queueWaitMs: number;
  queueDepthOnArrival: number;
  workerId: number;
  workerChecksum: number;
  responsePayload: Buffer;
};
