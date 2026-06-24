// metrics.controller.ts
import { Controller, Get, Res } from '@nestjs/common';
import { register } from './metric';

@Controller('/metrics')
export class MetricController {
  @Get()
  async metrics(@Res() res) {
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  }
}
