import { Controller, Get, Param, Query, Res } from '@nestjs/common';
import type { Response } from 'express';
import {
  RESPONSE_CONTENT_TYPE,
  SERVICE_NAME,
} from './resource-demand.constants';
import { ResourceDemandService } from './resource-demand.service';

@Controller('demand')
export class ResourceDemandController {
  constructor(
    private readonly resourceDemandService: ResourceDemandService,
  ) {}

  @Get()
  getRequestClassProfiles() {
    return {
      service: SERVICE_NAME,
      requestClassProfiles: this.resourceDemandService.getRequestClassProfiles(),
    };
  }

  @Get(':requestClass')
  async executeRequestClass(
    @Param('requestClass') requestClass: string,
    @Query('format') format: string | undefined,
    @Res() response: Response,
  ): Promise<void> {
    const execution =
      await this.resourceDemandService.executeRequestClass(requestClass);

    setExecutionHeaders(response, execution);

    if (format?.toLowerCase() === 'json') {
      response.status(200).json({
        service: SERVICE_NAME,
        requestClass: execution.requestClass,
        metrics: {
          targetThreadCpuMs: execution.targetThreadCpuMs,
          observedThreadCpuMs: execution.observedThreadCpuMs,
          responsePayloadBytes: execution.actualResponsePayloadBytes,
          appTimeMs: execution.appTimeMs,
          queueWaitMs: execution.queueWaitMs,
          queueDepthOnArrival: execution.queueDepthOnArrival,
          workerId: execution.workerId,
          workerChecksum: execution.workerChecksum,
        },
      });
      return;
    }

    response.type(RESPONSE_CONTENT_TYPE);
    response.status(200).end(execution.responsePayload);
  }
}

function setExecutionHeaders(
  response: Response,
  execution: {
    requestClass: string;
    targetThreadCpuMs: number;
    observedThreadCpuMs: number;
    targetResponsePayloadBytes: number;
    actualResponsePayloadBytes: number;
    appTimeMs: number;
    queueWaitMs: number;
    queueDepthOnArrival: number;
    workerId: number;
    workerChecksum: number;
  },
): void {
  response.setHeader('X-Service-Name', SERVICE_NAME);
  response.setHeader('X-Request-Class', execution.requestClass);
  response.setHeader(
    'X-Target-Thread-CPU-Ms',
    execution.targetThreadCpuMs.toFixed(3),
  );
  response.setHeader(
    'X-Observed-Thread-CPU-Ms',
    execution.observedThreadCpuMs.toFixed(3),
  );
  response.setHeader(
    'X-Target-Response-Payload-Bytes',
    String(execution.targetResponsePayloadBytes),
  );
  response.setHeader(
    'X-Actual-Response-Payload-Bytes',
    String(execution.actualResponsePayloadBytes),
  );
  response.setHeader(
    'Content-Length',
    String(execution.actualResponsePayloadBytes),
  );
  response.setHeader('X-Worker-Id', String(execution.workerId));
  response.setHeader('X-Worker-Checksum', String(execution.workerChecksum));
  response.setHeader('X-Queue-Wait-Ms', execution.queueWaitMs.toFixed(3));
  response.setHeader(
    'X-Queue-Depth-On-Arrival',
    String(execution.queueDepthOnArrival),
  );
  response.setHeader('X-App-Time-Ms', execution.appTimeMs.toFixed(3));
}
