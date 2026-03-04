// metrics.middleware.ts
import { Injectable, NestMiddleware } from '@nestjs/common';
import { httpRequestsTotal, httpRequestDuration } from './metric';

@Injectable()
export class MetricsMiddleware implements NestMiddleware {
  use(req: any, res: any, next: () => void) {
    const start = process.hrtime();

    res.on('finish', () => {
      const diff = process.hrtime(start);
      const duration = diff[0] + diff[1] / 1e9;

      const route = req.route?.path || req.url;

      httpRequestsTotal.inc({
        method: req.method,
        route,
        status: res.statusCode,
      });

      httpRequestDuration.observe(
        {
          method: req.method,
          route,
          status: res.statusCode,
        },
        duration,
      );
    });

    next();
  }
}
