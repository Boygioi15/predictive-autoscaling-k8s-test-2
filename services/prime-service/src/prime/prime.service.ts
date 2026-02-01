import { Injectable } from '@nestjs/common';

@Injectable()
export class PrimeService {
  // Hàm kiểm tra nguyên tố (Giữ nguyên để tốn CPU)
  private isPrime(num: number): boolean {
    if (num <= 1) return false;
    if (num <= 3) return true;
    if (num % 2 === 0 || num % 3 === 0) return false;

    for (let i = 5; i * i <= num; i += 6) {
      if (num % i === 0 || num % (i + 2) === 0) return false;
    }
    return true;
  }

  // Block 1: Đếm số lượng số nguyên tố từ 1 đến N
  countPrimesInRange(n: number): number {
    let count = 0;
    // Vòng lặp này chính là nơi CPU bị "đốt"
    for (let i = 2; i <= n; i++) {
      if (this.isPrime(i)) {
        count++;
      }
    }
    return count;
  }

  // Block 2: Tìm số nguyên tố thứ K (Giữ nguyên vì chỉ trả về 1 số)
  findKthPrime(k: number): number {
    let count = 0;
    let num = 2;
    while (count < k) {
      if (this.isPrime(num)) {
        count++;
      }
      if (count === k) return num;
      num++;
    }
    return -1;
  }

  // Block 3: Kiểm tra số N (Giữ nguyên)
  checkIsPrime(n: number): { isPrime: boolean; message: string } {
    const result = this.isPrime(n);
    return {
      isPrime: result,
      message: result
        ? `${n} là số nguyên tố`
        : `${n} không phải là số nguyên tố`,
    };
  }
}
