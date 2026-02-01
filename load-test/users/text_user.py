from locust import HttpUser, task, between
import random
from utils.payload import random_text

class TextUser(HttpUser):
    host = "http://localhost:3001"
    wait_time = between(1, 2)

    @task(2)
    def analyze_text(self):
        text = random_text(1000)
        self.client.post(
            "/text/analyze",
            json={"text": text},
            name="/text/analyze"
        )

    @task(1)
    def transform_text(self):
        text = random_text(200)
        self.client.post(
            "/text/transform?rounds=50",
            json={"text": text},
            name="/text/transform"
        )
