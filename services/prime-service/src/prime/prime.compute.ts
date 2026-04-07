export type PrimeTask =
  | { type: 'countPrimesInRange'; value: number }
  | { type: 'findKthPrime'; value: number }
  | { type: 'checkIsPrime'; value: number };

function isPrime(num: number): boolean {
  if (num <= 1) return false;
  if (num <= 3) return true;
  if (num % 2 === 0 || num % 3 === 0) return false;

  for (let i = 5; i * i <= num; i += 6) {
    if (num % i === 0 || num % (i + 2) === 0) return false;
  }

  return true;
}

export function countPrimesInRange(n: number): number {
  let count = 0;

  for (let i = 2; i <= n; i++) {
    if (isPrime(i)) {
      count++;
    }
  }

  return count;
}

export function findKthPrime(k: number): number {
  let count = 0;
  let num = 2;

  while (count < k) {
    if (isPrime(num)) {
      count++;
    }

    if (count === k) {
      return num;
    }

    num++;
  }

  return -1;
}

export function checkIsPrime(n: number): { isPrime: boolean; message: string } {
  const result = isPrime(n);

  return {
    isPrime: result,
    message: result ? `${n} la so nguyen to` : `${n} khong phai la so nguyen to`,
  };
}

export function executePrimeTask(task: PrimeTask) {
  switch (task.type) {
    case 'countPrimesInRange':
      return countPrimesInRange(task.value);
    case 'findKthPrime':
      return findKthPrime(task.value);
    case 'checkIsPrime':
      return checkIsPrime(task.value);
  }
}
