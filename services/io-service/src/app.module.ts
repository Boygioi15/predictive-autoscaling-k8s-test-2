import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { IoModule } from './io/io.module';
import { MetricModule } from './metric/metric.module';

@Module({
  imports: [IoModule, MetricModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
