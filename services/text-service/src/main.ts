import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { MetricsMiddleware } from './metric/metric.middleware';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.enableCors({
    origin: '*',
  });
  app.use(new MetricsMiddleware().use);
  await app.listen(process.env.PORT ?? 3000);
}
bootstrap();
