import { Injectable } from '@nestjs/common';
import { SERVICE_NAME } from './resource-demand/resource-demand.constants';

@Injectable()
export class AppService {
  getServiceSummary(requestClasses: string[]) {
    return {
      service: SERVICE_NAME,
      status: 'ok',
      requestClasses,
      endpoints: requestClasses.map((requestClass) => `/demand/${requestClass}`),
    };
  }
}
