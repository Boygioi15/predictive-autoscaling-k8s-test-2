import { Injectable } from '@nestjs/common';

@Injectable()
export class TextService {
  analyzeText(text: string) {
    // Tốn CPU + memory vừa phải
    const length = text.length;

    // Tách từ (regex nặng hơn split)
    const words = text.toLowerCase().match(/\b[\p{L}\p{N}']+\b/gu) || [];

    const sentences = text.split(/[.!?]+/);

    // Word frequency (tạo Map → tốn RAM)
    const freq = new Map<string, number>();
    for (const w of words) {
      freq.set(w, (freq.get(w) || 0) + 1);
    }

    // Lấy top 10 từ phổ biến
    const topWords = [...freq.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([word, count]) => ({ word, count }));

    return {
      length,
      totalWords: words.length,
      totalSentences: sentences.length,
      uniqueWords: freq.size,
      topWords,
    };
  }

  transformText(text: string, rounds: number) {
    let result = text;

    // Loop nhiều vòng để tăng CPU load
    for (let i = 0; i < rounds; i++) {
      result = result.split('').reverse().join('').toUpperCase();
    }

    return {
      originalLength: text.length,
      resultLength: result.length,
    };
  }
}
