import { Injectable } from '@nestjs/common';

const ONE_KIB = 1024;
const FILLER_PATTERN = Buffer.from('memory-pressure-seed');

export const MEMORY_PRESSURE_LIMITS = {
  minChunkSizeKb: 32,
  maxChunkSizeKb: 2048,
  minChunkCount: 1,
  maxChunkCount: 64,
  minHoldMs: 0,
  maxHoldMs: 5000,
} as const;

@Injectable()
export class TextService {
  analyzeText(text: string) {
    const length = text.length;
    const words = text.toLowerCase().match(/\b[\p{L}\p{N}']+\b/gu) || [];
    const sentences = text.split(/[.!?]+/);
    const freq = new Map<string, number>();
    for (const w of words) {
      freq.set(w, (freq.get(w) || 0) + 1);
    }
    const topWords = [...freq.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([word, count]) => ({ word, count }));

    return {
      length,
      totalWords: words.length,
      totalSentences: sentences.length,
      uniqueWords: freq.size,
      topWords,
    };
  }

  transformText(text: string, rounds: number) {
    let result = text;

    for (let i = 0; i < rounds; i++) {
      result = result.split('').reverse().join('').toUpperCase();
    }

    return {
      originalLength: text.length,
      resultLength: result.length,
    };
  }

  async createMemoryPressure(
    text: string,
    chunkSizeKb: number,
    chunkCount: number,
    holdMs: number,
  ) {
    const normalized = text.trim();
    const source = Buffer.from(normalized, 'utf-8');
    const words = normalized.toLowerCase().match(/\b[\p{L}\p{N}']+\b/gu) || [];
    const freq = new Map<string, number>();

    for (const word of words) {
      freq.set(word, (freq.get(word) || 0) + 1);
    }

    const chunkSizeBytes = chunkSizeKb * ONE_KIB;
    const workingSet: Buffer[] = [];
    let checksum = 0;

    for (let index = 0; index < chunkCount; index++) {
      const chunk = Buffer.alloc(chunkSizeBytes);
      fillChunk(chunk, source, index);
      workingSet.push(chunk);

      const sampleOffset = Math.min(chunk.length - 1, (index * 97) % chunk.length);
      checksum = (checksum + chunk[sampleOffset] + chunk[chunk.length - 1]) % 1_000_000_007;
    }

    if (holdMs > 0) {
      await sleep(holdMs);
    }

    return {
      inputBytes: source.byteLength,
      chunkSizeKb,
      chunkCount,
      workingSetBytes: chunkSizeBytes * chunkCount,
      holdMs,
      uniqueWords: freq.size,
      topWords: [...freq.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([word, count]) => ({ word, count })),
      checksum,
    };
  }
}

function fillChunk(target: Buffer, source: Buffer, seed: number): void {
  let offset = 0;
  const seedByte = seed % 251;

  while (offset < target.length) {
    if (source.length > 0) {
      const copied = source.copy(target, offset, 0, Math.min(source.length, target.length - offset));
      offset += copied;
    }

    if (offset >= target.length) {
      break;
    }

    const fillerLength = Math.min(FILLER_PATTERN.length, target.length - offset);
    FILLER_PATTERN.copy(target, offset, 0, fillerLength);
    offset += fillerLength;
  }

  if (target.length > 0) {
    target[0] = (target[0] + seedByte) % 255;
  }
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
