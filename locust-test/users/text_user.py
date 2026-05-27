from locust import HttpUser, task, between

from workload import DEFAULT_TARGET_HOST, analyze_text_request, transform_text_request

class TextUser(HttpUser):
    abstract = True
    host = DEFAULT_TARGET_HOST
    wait_time = between(1, 2)

    @task(1)
    def analyze_text(self):
        analyze_text_request(self.client)

    @task(1)
    def transform_text(self):
        transform_text_request(self.client)
