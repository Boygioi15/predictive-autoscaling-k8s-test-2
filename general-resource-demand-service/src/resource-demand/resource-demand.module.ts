import { Module } from '@nestjs/common';
import { ResourceDemandController } from './resource-demand.controller';
import { ResourceDemandService } from './resource-demand.service';

@Module({
  providers: [ResourceDemandService],
  controllers: [ResourceDemandController],
  exports: [ResourceDemandService],
})
export class ResourceDemandModule {}
