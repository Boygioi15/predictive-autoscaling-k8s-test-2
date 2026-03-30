import { Controller, Get, Query, BadRequestException } from '@nestjs/common';
import { PrimeService } from './prime.service';

@Controller('prime')
export class PrimeController {
  // simple in-memory counter for each route
  private static routeCounts = { range: 0, kth: 0, check: 0 };

  constructor(private readonly primeService: PrimeService) {}

  // API 1: /prime/range?n=100000
  @Get('range')
  getPrimesCountInRange(@Query('n') n: string) {
    // increment and log counter
    PrimeController.routeCounts.range++;
    console.log(`[prime/range] called ${PrimeController.routeCounts.range} times`);

    const num = parseInt(n);
    if (isNaN(num) || num < 0)
      throw new BadRequestException('N phải là số dương');

    const start = Date.now();

    // Gọi hàm đếm thay vì hàm tìm mảng
    const count = this.primeService.countPrimesInRange(num);

    const end = Date.now();
    return {
      input: num,
      totalPrimesFound: count, // Trả về số lượng
      timeTaken: `${end - start}ms`, // Thời gian CPU xử lý
    };
  }

  // API 2: /prime/kth (Giữ nguyên)
  @Get('kth')
  getKthPrime(@Query('k') k: string) {
    PrimeController.routeCounts.kth++;
    console.log(`[prime/kth] called ${PrimeController.routeCounts.kth} times`);

    const num = parseInt(k);
    if (isNaN(num) || num <= 0)
      throw new BadRequestException('K phải là số dương > 0');

    const start = Date.now();
    const result = this.primeService.findKthPrime(num);
    const end = Date.now();

    return {
      inputK: num,
      result: result,
      timeTaken: `${end - start}ms`,
    };
  }

  // API 3: /prime/check (Giữ nguyên)
  @Get('check')
  checkPrime(@Query('n') n: string) {
    PrimeController.routeCounts.check++;
    console.log(`[prime/check] called ${PrimeController.routeCounts.check} times`);

    const num = parseInt(n);
    if (isNaN(num)) throw new BadRequestException('N phải là số');

    return this.primeService.checkIsPrime(num);
  }
}
