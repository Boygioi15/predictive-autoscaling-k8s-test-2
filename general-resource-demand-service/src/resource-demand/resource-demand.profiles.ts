import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  CPU_DEMAND_PROFILES_PATH,
  RESPONSE_PAYLOAD_DEMAND_PROFILES_PATH,
} from './resource-demand.constants';
import {
  CpuDemandConfig,
  CpuDemandProfile,
  RequestClassProfile,
  ResponsePayloadPercentileProfile,
  SampledRequestClassDemand,
} from './resource-demand.types';

export function loadRequestClassProfiles(): Map<string, RequestClassProfile> {
  const serviceRoot = resolve(__dirname, '..', '..');
  const cpuProfilesPath = resolve(serviceRoot, CPU_DEMAND_PROFILES_PATH);
  const responsePayloadProfilesPath = resolve(
    serviceRoot,
    RESPONSE_PAYLOAD_DEMAND_PROFILES_PATH,
  );

  const cpuDemandConfig = loadCpuDemandConfig(
    cpuProfilesPath,
    'CPU demand',
  );
  const responsePayloadDemandProfiles = loadResponsePayloadPercentileProfileList(
    responsePayloadProfilesPath,
    'response payload demand',
  );
  const responsePayloadProfilesByClass = new Map(
    responsePayloadDemandProfiles.map((profile) => [profile.requestClass, profile]),
  );
  const profilesByClass = new Map<string, RequestClassProfile>();

  for (const [requestClass, cpuWeight] of Object.entries(
    cpuDemandConfig.requestClassWeights,
  )) {
    const responsePayloadDemandProfile = responsePayloadProfilesByClass.get(
      requestClass,
    );

    if (!responsePayloadDemandProfile) {
      continue;
    }

    profilesByClass.set(requestClass, {
      requestClass,
      cpuDemandProfile: {
        requestClass,
        baseThreadCpuMs: cpuDemandConfig.baseThreadCpuMs,
        cpuWeight,
        cpuNoiseLimitMs: cpuDemandConfig.cpuNoiseLimitMs,
      },
      responsePayloadDemandProfile,
    });
  }

  if (profilesByClass.size === 0) {
    throw new Error(
      'No request classes were activated because the CPU demand profiles and response payload demand profiles do not overlap',
    );
  }

  return profilesByClass;
}

export function sampleRequestClassDemand(
  profile: RequestClassProfile,
): SampledRequestClassDemand {
  const sampledThreadCpuMs = sampleCpuDemand(profile.cpuDemandProfile);
  const sampledResponsePayloadBytes =
    sampleResponsePayloadBytesFromPercentiles(
      profile.responsePayloadDemandProfile,
    );

  return {
    requestClass: profile.requestClass,
    targetThreadCpuMs: sampledThreadCpuMs,
    targetThreadCpuTimeNs: Math.max(1, Math.round(sampledThreadCpuMs * 1e6)),
    targetResponsePayloadBytes: sampledResponsePayloadBytes,
  };
}

function loadCpuDemandConfig(
  filePath: string,
  profileLabel: string,
): CpuDemandConfig {
  const rawPayload = readFileSync(filePath, 'utf8');
  const parsedPayload = JSON.parse(rawPayload) as unknown;

  return validateCpuDemandConfig(parsedPayload, profileLabel);
}

function loadResponsePayloadPercentileProfileList(
  filePath: string,
  profileLabel: string,
): ResponsePayloadPercentileProfile[] {
  const rawPayload = readFileSync(filePath, 'utf8');
  const parsedPayload = JSON.parse(rawPayload) as unknown;

  if (!Array.isArray(parsedPayload) || parsedPayload.length === 0) {
    throw new Error(`${profileLabel} profiles must be a non-empty JSON array`);
  }

  const requestClasses = new Set<string>();

  return parsedPayload.map((entry, index) => {
    const profile = validateResponsePayloadPercentileProfile(
      entry,
      profileLabel,
      index,
    );

    if (requestClasses.has(profile.requestClass)) {
      throw new Error(
        `${profileLabel} profiles contain duplicate request class '${profile.requestClass}'`,
      );
    }

    requestClasses.add(profile.requestClass);
    return profile;
  });
}

function validateCpuDemandConfig(
  value: unknown,
  profileLabel: string,
): CpuDemandConfig {
  if (!value || typeof value !== 'object') {
    throw new Error(`${profileLabel} config must be an object`);
  }

  const candidate = value as Record<string, unknown>;
  const baseThreadCpuMs = validateNumber(
    candidate.baseThreadCpuMs,
    `${profileLabel} baseThreadCpuMs`,
    0,
  );
  const cpuNoiseLimitMs = validateNumber(
    candidate.cpuNoiseLimitMs,
    `${profileLabel} cpuNoiseLimitMs`,
    0,
  );
  const requestClassWeights = validateRequestClassWeights(
    candidate.requestClassWeights,
    profileLabel,
  );

  if (baseThreadCpuMs <= 0) {
    throw new Error(`${profileLabel} baseThreadCpuMs must be > 0`);
  }

  if (cpuNoiseLimitMs < 0) {
    throw new Error(`${profileLabel} cpuNoiseLimitMs must be >= 0`);
  }

  return {
    baseThreadCpuMs,
    cpuNoiseLimitMs,
    requestClassWeights,
  };
}

function validateRequestClassWeights(
  value: unknown,
  profileLabel: string,
): Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${profileLabel} requestClassWeights must be an object`);
  }

  const candidate = value as Record<string, unknown>;
  const entries = Object.entries(candidate);

  if (entries.length === 0) {
    throw new Error(`${profileLabel} requestClassWeights must not be empty`);
  }

  return Object.fromEntries(
    entries.map(([rawRequestClass, rawCpuWeight]) => {
      const requestClass = rawRequestClass.trim().toLowerCase();

      if (!/^[a-z0-9._-]+$/.test(requestClass)) {
        throw new Error(
          `${profileLabel} requestClassWeights contains an invalid request class '${rawRequestClass}'`,
        );
      }

      const cpuWeight = validateNumber(
        rawCpuWeight,
        `${profileLabel} cpuWeight for '${requestClass}'`,
        0,
      );

      if (cpuWeight <= 0) {
        throw new Error(
          `${profileLabel} cpuWeight for '${requestClass}' must be > 0`,
        );
      }

      return [requestClass, cpuWeight];
    }),
  );
}

function validateResponsePayloadPercentileProfile(
  value: unknown,
  profileLabel: string,
  index: number,
): ResponsePayloadPercentileProfile {
  if (!value || typeof value !== 'object') {
    throw new Error(
      `${profileLabel} profile at index ${index} must be an object`,
    );
  }

  const candidate = value as Record<string, unknown>;
  const requestClass = String(candidate.requestClass ?? '')
    .trim()
    .toLowerCase();

  if (!/^[a-z0-9._-]+$/.test(requestClass)) {
    throw new Error(
      `${profileLabel} profile at index ${index} must define a valid requestClass`,
    );
  }

  const p01Bytes = validateNumber(candidate.p01Bytes, `${profileLabel} p01Bytes`, index);
  const p05Bytes = validateNumber(candidate.p05Bytes, `${profileLabel} p05Bytes`, index);
  const p10Bytes = validateNumber(candidate.p10Bytes, `${profileLabel} p10Bytes`, index);
  const p25Bytes = validateNumber(candidate.p25Bytes, `${profileLabel} p25Bytes`, index);
  const p50Bytes = validateNumber(candidate.p50Bytes, `${profileLabel} p50Bytes`, index);
  const p75Bytes = validateNumber(candidate.p75Bytes, `${profileLabel} p75Bytes`, index);
  const p90Bytes = validateNumber(candidate.p90Bytes, `${profileLabel} p90Bytes`, index);
  const p95Bytes = validateNumber(candidate.p95Bytes, `${profileLabel} p95Bytes`, index);
  const p99Bytes = validateNumber(candidate.p99Bytes, `${profileLabel} p99Bytes`, index);
  const percentileValues = [
    p01Bytes,
    p05Bytes,
    p10Bytes,
    p25Bytes,
    p50Bytes,
    p75Bytes,
    p90Bytes,
    p95Bytes,
    p99Bytes,
  ];

  for (const percentileValue of percentileValues) {
    if (percentileValue < 0) {
      throw new Error(
        `${profileLabel} percentile values at index ${index} must be >= 0`,
      );
    }
  }

  for (let percentileIndex = 1; percentileIndex < percentileValues.length; percentileIndex++) {
    if (percentileValues[percentileIndex] < percentileValues[percentileIndex - 1]) {
      throw new Error(
        `${profileLabel} percentile values at index ${index} must be non-decreasing`,
      );
    }
  }

  return {
    requestClass,
    p01Bytes,
    p05Bytes,
    p10Bytes,
    p25Bytes,
    p50Bytes,
    p75Bytes,
    p90Bytes,
    p95Bytes,
    p99Bytes,
  };
}

function validateNumber(
  value: unknown,
  label: string,
  index: number,
): number {
  if (typeof value !== 'number' || Number.isNaN(value) || !Number.isFinite(value)) {
    throw new Error(`${label} at index ${index} must be a finite number`);
  }

  return value;
}

function sampleCpuDemand(profile: CpuDemandProfile): number {
  const baseThreadCpuMs = profile.baseThreadCpuMs * profile.cpuWeight;
  const noiseMs = sampleDouble(-profile.cpuNoiseLimitMs, profile.cpuNoiseLimitMs);

  return Math.max(0.001, baseThreadCpuMs + noiseMs);
}

function sampleResponsePayloadBytesFromPercentiles(
  profile: ResponsePayloadPercentileProfile,
): number {
  const percentileSteps: Array<{ percentile: number; bytes: number }> = [
    { percentile: 1, bytes: profile.p01Bytes },
    { percentile: 5, bytes: profile.p05Bytes },
    { percentile: 10, bytes: profile.p10Bytes },
    { percentile: 25, bytes: profile.p25Bytes },
    { percentile: 50, bytes: profile.p50Bytes },
    { percentile: 75, bytes: profile.p75Bytes },
    { percentile: 90, bytes: profile.p90Bytes },
    { percentile: 95, bytes: profile.p95Bytes },
    { percentile: 99, bytes: profile.p99Bytes },
  ];
  const percentileRoll = randomIntInclusive(1, 100);

  if (percentileRoll >= 99) {
    return Math.max(0, Math.round(profile.p99Bytes));
  }

  let lowerStep = percentileSteps[0];
  let upperStep = percentileSteps[1];

  for (let stepIndex = 1; stepIndex < percentileSteps.length; stepIndex++) {
    const step = percentileSteps[stepIndex];

    if (percentileRoll < step.percentile) {
      upperStep = step;
      break;
    }

    lowerStep = step;
    upperStep = percentileSteps[Math.min(stepIndex + 1, percentileSteps.length - 1)];
  }

  const lowerBound = Math.round(lowerStep.bytes);
  const upperBound = Math.round(upperStep.bytes);

  return randomIntInclusive(
    Math.min(lowerBound, upperBound),
    Math.max(lowerBound, upperBound),
  );
}

function randomIntInclusive(min: number, max: number): number {
  if (max <= min) {
    return min;
  }

  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function sampleDouble(min: number, max: number): number {
  if (max <= min) {
    return min;
  }

  return Math.random() * (max - min) + min;
}
