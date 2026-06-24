import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { MetricsMiddleware } from './metric/metric.middleware';
import { APP_PORT } from './resource-demand/resource-demand.constants';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.enableCors({
    origin: '*',
  });
  app.use(new MetricsMiddleware().use);
  await app.listen(APP_PORT);
}
bootstrap();
