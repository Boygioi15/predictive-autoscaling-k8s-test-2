import { Controller, Get } from '@nestjs/common';
import { AppService } from './app.service';
import { ResourceDemandService } from './resource-demand/resource-demand.service';

@Controller()
export class AppController {
  constructor(
    private readonly appService: AppService,
    private readonly resourceDemandService: ResourceDemandService,
  ) {}

  @Get()
  getServiceSummary() {
    return this.appService.getServiceSummary(
      this.resourceDemandService.getRequestClasses(),
    );
  }
}
