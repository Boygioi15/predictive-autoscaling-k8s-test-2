from locust import HttpUser, task, between
import random

class PrimeUser(HttpUser):
    host = "http://prime-service:3000"
    wait_time = between(1, 3)


    @task(1)
    def range_prime(self):
        n = random.randint(1_000_000, 10_000_000)
        self.client.get(
            f"/prime/range?n={n}",
            name="/prime/range"
        )
    @task(1)
    def check_prime(self):
        n = random.randint(1_000_000, 10_000_000)
        self.client.get(
            f"/prime/check?n={n}",
            name="/prime/check"
        )

    @task(1)
    def kth_prime(self):
        k = random.randint(5000, 15000)
        self.client.get(
            f"/prime/kth?k={k}",
            name="/prime/kth"
        )
