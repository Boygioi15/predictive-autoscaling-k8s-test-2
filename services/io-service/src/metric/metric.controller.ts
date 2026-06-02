import { Controller, Get, Res } from '@nestjs/common';
import { renderMetrics } from './metric';

@Controller('/metrics')
export class MetricController {
  @Get()
  async metrics(@Res() res) {
    res.set('Content-Type', 'text/plain; version=0.0.4; charset=utf-8');
    res.end(renderMetrics());
  }
}
