from locust import HttpUser, task, constant
from workload import (
    DEFAULT_TARGET_HOST,
    check_prime_request,
    kth_prime_request,
    range_prime_request,
)

class PrimeUser(HttpUser):
    abstract = True
    host = DEFAULT_TARGET_HOST
    wait_time = constant(1)

    @task(1)
    def range_prime(self):
        range_prime_request(self.client)

    @task(1)
    def kth_prime(self):
        kth_prime_request(self.client)

    @task(1)
    def check_prime(self):
        check_prime_request(self.client)
