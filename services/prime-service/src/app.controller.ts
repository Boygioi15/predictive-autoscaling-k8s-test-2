import { Controller, Get } from '@nestjs/common';
import { AppService } from './app.service';

@Controller()
export class AppController {
  private static count = 0;

  constructor(private readonly appService: AppService) {}

  @Get()
  getHello(): string {
    AppController.count++;
    console.log(`[root] getHello called ${AppController.count} times`);
    return this.appService.getHello();
  }
}
