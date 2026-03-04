import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { TextModule } from './text/text.module';
import { PrometheusModule } from '@willsoto/nestjs-prometheus';
import { MetricModule } from './metric/metric.module';

@Module({
  imports: [
    TextModule,
    PrometheusModule.register({
      defaultMetrics: {
        enabled: true, // Bật thu thập CPU/RAM mặc định
      },
    }),
    MetricModule,
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
