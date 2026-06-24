import { Module } from '@nestjs/common';
import { MetricController } from './metric.controller';
import { MetricsMiddleware } from './metric.middleware';

@Module({
  controllers: [MetricController],
  providers: [MetricsMiddleware],
  exports: [MetricsMiddleware],
})
export class MetricModule {}
