import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { IoModule } from './io/io.module';

@Module({
  imports: [IoModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
