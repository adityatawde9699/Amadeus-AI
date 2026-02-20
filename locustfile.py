"""
Locust load testing script for Amadeus AI.

Run with:
    locust -f locustfile.py --host=http://localhost:8000
"""

from locust import HttpUser, task, between
import json

class AmadeusUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        """Called when a user starts. We can set up auth tokens here."""
        self.headers = {"Content-Type": "application/json"}
        # In a real scenario, we would acquire a JWT token here
        # self.headers["Authorization"] = f"Bearer {token}"

    @task(3)
    def check_health(self):
        """Test health endpoints frequently."""
        self.client.get("/health")

    @task(1)
    def check_system_detailed(self):
        """Test the system status, hits psutil."""
        self.client.get("/health/system")

    @task(2)
    def get_tasks(self):
        """Test retrieving tasks list."""
        self.client.get("/api/v1/tasks", headers=self.headers)

    @task(1)
    def simulate_chat(self):
        """Simulate a chat request."""
        payload = {
            "message": "Hello Amadeus, what's my schedule today?",
            "source": "api"
        }
        self.client.post("/api/v1/chat", json=payload, headers=self.headers)
