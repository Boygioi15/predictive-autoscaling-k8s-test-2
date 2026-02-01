import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { TextModule } from './text/text.module';

@Module({
  imports: [TextModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
