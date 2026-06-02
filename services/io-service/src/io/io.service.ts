import { Injectable, OnModuleInit } from '@nestjs/common';
import { mkdir, open, readFile, stat, writeFile } from 'node:fs/promises';
import { basename, join } from 'node:path';
import { recordFileOperation } from '../metric/metric';

const ONE_KIB = 1024;
const PAYLOAD_PATTERN = Buffer.from('io-volume-pattern');

export const IO_LIMITS = {
  minSizeKb: 64,
  maxSizeKb: 4096,
  minSegments: 1,
  maxSegments: 16,
  minHoldMs: 0,
  maxHoldMs: 5000,
} as const;

@Injectable()
export class IoService implements OnModuleInit {
  private readonly storageRoot =
    process.env.IO_STORAGE_PATH ?? '/tmp/predictive-autoscaling-io';

  async onModuleInit(): Promise<void> {
    await mkdir(this.storageRoot, { recursive: true });
  }

  async writeFileWorkload(
    fileId: string,
    sizeKb: number,
    segments: number,
    holdMs: number,
  ) {
    const safeFileId = sanitizeFileId(fileId);
    const payload = buildPayload(safeFileId, sizeKb);
    const filePath = this.resolveFilePath(safeFileId, sizeKb);
    const segmentSize = Math.max(ONE_KIB, Math.ceil(payload.length / segments));
    const start = Date.now();
    let bytesWritten = 0;

    await mkdir(this.storageRoot, { recursive: true });
    const handle = await open(filePath, 'w');

    try {
      for (let offset = 0; offset < payload.length; offset += segmentSize) {
        const chunk = payload.subarray(
          offset,
          Math.min(offset + segmentSize, payload.length),
        );
        const result = await handle.write(chunk, 0, chunk.length, offset);
        bytesWritten += result.bytesWritten;
      }

      await handle.sync();
    } finally {
      await handle.close();
    }

    if (holdMs > 0) {
      await sleep(holdMs);
    }

    recordFileOperation('write', bytesWritten, (Date.now() - start) / 1000);

    return {
      operation: 'write',
      fileId: safeFileId,
      sizeKb,
      segments,
      bytesWritten,
      checksum: checksumPayload(payload),
      storageKey: basename(filePath),
    };
  }

  async readFileWorkload(fileId: string, sizeKb: number, holdMs: number) {
    const safeFileId = sanitizeFileId(fileId);
    const filePath = await this.ensureSeedFile(safeFileId, sizeKb);
    const start = Date.now();
    const payload = await readFile(filePath);

    if (holdMs > 0) {
      await sleep(holdMs);
    }

    recordFileOperation('read', payload.length, (Date.now() - start) / 1000);

    return {
      operation: 'read',
      fileId: safeFileId,
      sizeKb: Math.ceil(payload.length / ONE_KIB),
      bytesRead: payload.length,
      checksum: checksumPayload(payload),
      storageKey: basename(filePath),
    };
  }

  private resolveFilePath(fileId: string, sizeKb: number): string {
    return join(this.storageRoot, `${fileId}-${sizeKb}kb.bin`);
  }

  private async ensureSeedFile(fileId: string, sizeKb: number): Promise<string> {
    const filePath = this.resolveFilePath(fileId, sizeKb);
    const targetBytes = sizeKb * ONE_KIB;

    try {
      const existing = await stat(filePath);
      if (existing.size === targetBytes) {
        return filePath;
      }
    } catch {
      // Fall through and create the file when it does not exist yet.
    }

    await mkdir(this.storageRoot, { recursive: true });
    await writeFile(filePath, buildPayload(fileId, sizeKb));

    return filePath;
  }
}

export function sanitizeFileId(fileId: string): string {
  const normalized = fileId.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-');
  return normalized.length > 0 ? normalized : 'slot-0';
}

function buildPayload(fileId: string, sizeKb: number): Buffer {
  const payload = Buffer.alloc(sizeKb * ONE_KIB);
  const seed = Buffer.from(`${fileId}|${sizeKb}|io-workload`, 'utf-8');
  let offset = 0;

  while (offset < payload.length) {
    const seedLength = Math.min(seed.length, payload.length - offset);
    seed.copy(payload, offset, 0, seedLength);
    offset += seedLength;

    if (offset >= payload.length) {
      break;
    }

    const fillerLength = Math.min(PAYLOAD_PATTERN.length, payload.length - offset);
    PAYLOAD_PATTERN.copy(payload, offset, 0, fillerLength);
    offset += fillerLength;
  }

  return payload;
}

function checksumPayload(payload: Buffer): number {
  let checksum = 0;
  const stride = Math.max(1, Math.floor(payload.length / 128));

  for (let index = 0; index < payload.length; index += stride) {
    checksum = (checksum + payload[index] * (index + 1)) % 1_000_000_007;
  }

  return checksum;
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
