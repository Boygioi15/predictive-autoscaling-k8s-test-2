import { Test, TestingModule } from '@nestjs/testing';
import { IoController } from './io.controller';
import { IoService } from './io.service';

describe('IoController', () => {
  let controller: IoController;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      controllers: [IoController],
      providers: [IoService],
    }).compile();

    controller = module.get<IoController>(IoController);
  });

  it('should be defined', () => {
    expect(controller).toBeDefined();
  });
});
