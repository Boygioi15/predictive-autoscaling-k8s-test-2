import { Injectable, NestMiddleware } from '@nestjs/common';
import { recordHttpRequest } from './metric';

@Injectable()
export class MetricsMiddleware implements NestMiddleware {
  use(req: any, res: any, next: () => void) {
    const start = process.hrtime();

    res.on('finish', () => {
      const diff = process.hrtime(start);
      const durationSeconds = diff[0] + diff[1] / 1e9;

      recordHttpRequest(
        {
          method: req.method,
          route: req.route?.path || req.path || req.url,
          status: res.statusCode,
        },
        durationSeconds,
      );
    });

    next();
  }
}
