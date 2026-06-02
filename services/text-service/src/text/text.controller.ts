import {
  BadRequestException,
  Body,
  Controller,
  Post,
  Query,
} from '@nestjs/common';
import { MEMORY_PRESSURE_LIMITS, TextService } from './text.service';

@Controller('text')
export class TextController {
  constructor(private readonly textService: TextService) {}

  @Post('analyze')
  analyze(@Body('text') text: string) {
    if (!text || text.length === 0) {
      throw new BadRequestException('Text không được rỗng');
    }

    const start = Date.now();
    const result = this.textService.analyzeText(text);
    const end = Date.now();

    return {
      inputSize: text.length,
      analysis: result,
      timeTaken: `${end - start}ms`,
    };
  }

  @Post('transform')
  transform(@Body('text') text: string, @Query('rounds') rounds = '50') {
    if (!text || text.length === 0) {
      throw new BadRequestException('Text không được rỗng');
    }

    const r = parseInt(rounds, 10);
    if (isNaN(r) || r <= 0) {
      throw new BadRequestException('rounds phải là số > 0');
    }

    const start = Date.now();
    const result = this.textService.transformText(text, r);
    const end = Date.now();

    return {
      rounds: r,
      ...result,
      timeTaken: `${end - start}ms`,
    };
  }

  @Post('pressure')
  async pressure(
    @Body('text') text: string,
    @Query('chunkSizeKb') chunkSizeKb = '256',
    @Query('chunkCount') chunkCount = '12',
    @Query('holdMs') holdMs = '25',
  ) {
    if (!text || text.length === 0) {
      throw new BadRequestException('Text không được rỗng');
    }

    const parsedChunkSizeKb = parseInt(chunkSizeKb, 10);
    const parsedChunkCount = parseInt(chunkCount, 10);
    const parsedHoldMs = parseInt(holdMs, 10);

    if (
      isNaN(parsedChunkSizeKb) ||
      parsedChunkSizeKb < MEMORY_PRESSURE_LIMITS.minChunkSizeKb ||
      parsedChunkSizeKb > MEMORY_PRESSURE_LIMITS.maxChunkSizeKb
    ) {
      throw new BadRequestException(
        `chunkSizeKb phải nằm trong khoảng ${MEMORY_PRESSURE_LIMITS.minChunkSizeKb}-${MEMORY_PRESSURE_LIMITS.maxChunkSizeKb}`,
      );
    }

    if (
      isNaN(parsedChunkCount) ||
      parsedChunkCount < MEMORY_PRESSURE_LIMITS.minChunkCount ||
      parsedChunkCount > MEMORY_PRESSURE_LIMITS.maxChunkCount
    ) {
      throw new BadRequestException(
        `chunkCount phải nằm trong khoảng ${MEMORY_PRESSURE_LIMITS.minChunkCount}-${MEMORY_PRESSURE_LIMITS.maxChunkCount}`,
      );
    }

    if (
      isNaN(parsedHoldMs) ||
      parsedHoldMs < MEMORY_PRESSURE_LIMITS.minHoldMs ||
      parsedHoldMs > MEMORY_PRESSURE_LIMITS.maxHoldMs
    ) {
      throw new BadRequestException(
        `holdMs phải nằm trong khoảng ${MEMORY_PRESSURE_LIMITS.minHoldMs}-${MEMORY_PRESSURE_LIMITS.maxHoldMs}`,
      );
    }

    const start = Date.now();
    const result = await this.textService.createMemoryPressure(
      text,
      parsedChunkSizeKb,
      parsedChunkCount,
      parsedHoldMs,
    );
    const end = Date.now();

    return {
      ...result,
      timeTaken: `${end - start}ms`,
    };
  }
}
