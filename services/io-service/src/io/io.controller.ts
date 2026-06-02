import {
  BadRequestException,
  Controller,
  Get,
  Post,
  Query,
} from '@nestjs/common';
import { IO_LIMITS, IoService } from './io.service';

@Controller('io')
export class IoController {
  constructor(private readonly ioService: IoService) {}

  @Post('write')
  async write(
    @Query('fileId') fileId = 'slot-0',
    @Query('sizeKb') sizeKb = '256',
    @Query('segments') segments = '4',
    @Query('holdMs') holdMs = '10',
  ) {
    const parsedSizeKb = parseRange('sizeKb', sizeKb, IO_LIMITS.minSizeKb, IO_LIMITS.maxSizeKb);
    const parsedSegments = parseRange('segments', segments, IO_LIMITS.minSegments, IO_LIMITS.maxSegments);
    const parsedHoldMs = parseRange('holdMs', holdMs, IO_LIMITS.minHoldMs, IO_LIMITS.maxHoldMs);

    const start = Date.now();
    const result = await this.ioService.writeFileWorkload(
      fileId,
      parsedSizeKb,
      parsedSegments,
      parsedHoldMs,
    );
    const end = Date.now();

    return {
      ...result,
      timeTaken: `${end - start}ms`,
    };
  }

  @Get('read')
  async read(
    @Query('fileId') fileId = 'slot-0',
    @Query('sizeKb') sizeKb = '256',
    @Query('holdMs') holdMs = '10',
  ) {
    const parsedSizeKb = parseRange('sizeKb', sizeKb, IO_LIMITS.minSizeKb, IO_LIMITS.maxSizeKb);
    const parsedHoldMs = parseRange('holdMs', holdMs, IO_LIMITS.minHoldMs, IO_LIMITS.maxHoldMs);

    const start = Date.now();
    const result = await this.ioService.readFileWorkload(
      fileId,
      parsedSizeKb,
      parsedHoldMs,
    );
    const end = Date.now();

    return {
      ...result,
      timeTaken: `${end - start}ms`,
    };
  }
}

function parseRange(
  field: string,
  rawValue: string,
  min: number,
  max: number,
): number {
  const parsed = parseInt(rawValue, 10);

  if (isNaN(parsed) || parsed < min || parsed > max) {
    throw new BadRequestException(`${field} phải nằm trong khoảng ${min}-${max}`);
  }

  return parsed;
}
