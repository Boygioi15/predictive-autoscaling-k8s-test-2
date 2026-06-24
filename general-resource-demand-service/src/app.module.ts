import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { PrometheusModule } from '@willsoto/nestjs-prometheus';
import { MetricModule } from './metric/metric.module';
import { ResourceDemandModule } from './resource-demand/resource-demand.module';

@Module({
  imports: [
    ResourceDemandModule,
    PrometheusModule.register({
      defaultMetrics: {
        enabled: true,
      },
    }),
    MetricModule,
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
