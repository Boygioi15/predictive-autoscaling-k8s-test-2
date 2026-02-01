import { Controller } from '@nestjs/common';
import { IoService } from './io.service';

@Controller('io')
export class IoController {
  constructor(private readonly ioService: IoService) {}
}
