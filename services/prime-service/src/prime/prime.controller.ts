import { Controller, Get, Query, BadRequestException } from '@nestjs/common';
import { PrimeService } from './prime.service';

@Controller()
export class PrimeController {
  constructor(private readonly primeService: PrimeService) {}

  @Get('range')
  async getPrimesCountInRange(@Query('n') n: string) {
    const num = parseInt(n, 10);
    if (isNaN(num) || num < 0)
      throw new BadRequestException('N phải là số dương');

    const start = Date.now();

    const count = await this.primeService.countPrimesInRange(num);

    const end = Date.now();
    return {
      input: num,
      totalPrimesFound: count,
      timeTaken: `${end - start}ms`,
    };
  }

  @Get('kth')
  async getKthPrime(@Query('k') k: string) {
    const num = parseInt(k, 10);
    if (isNaN(num) || num <= 0)
      throw new BadRequestException('K phải là số dương > 0');

    const start = Date.now();
    const result = await this.primeService.findKthPrime(num);
    const end = Date.now();

    return {
      inputK: num,
      result: result,
      timeTaken: `${end - start}ms`,
    };
  }

  @Get('check')
  async checkPrime(@Query('n') n: string) {
    const num = parseInt(n, 10);
    if (isNaN(num)) throw new BadRequestException('N phải là số');

    return this.primeService.checkIsPrime(num);
  }
}
