import {
  BadRequestException,
  Body,
  Controller,
  Post,
  Query,
} from '@nestjs/common';
import { TextService } from './text.service';

@Controller('text')
export class TextController {
  // track request counts per endpoint
  private static routeCounts = { analyze: 0, transform: 0 };

  constructor(private readonly textService: TextService) {}

  // POST /text/analyze
  @Post('analyze')
  analyze(@Body('text') text: string) {
    TextController.routeCounts.analyze++;
    console.log(`[text/analyze] called ${TextController.routeCounts.analyze} times`);

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

  // POST /text/transform?rounds=100
  @Post('transform')
  transform(@Body('text') text: string, @Query('rounds') rounds = '50') {
    TextController.routeCounts.transform++;
    console.log(`[text/transform] called ${TextController.routeCounts.transform} times`);

    const r = parseInt(rounds);
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
}
