"""
Locust load testing script for Amadeus AI.

Run with:
    locust -f locustfile.py --host=http://localhost:8000
"""


from locust import HttpUser, between, task


class AmadeusUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        """Called when a user starts. Acquire a JWT token via the auth endpoint."""
        self.headers = {"Content-Type": "application/json"}

        # Register a test user (ignored if already exists) and log in to get a JWT
        test_email = "loadtest@amadeus.local"
        test_password = "LoadTest!SecurePass123"

        # Attempt registration (may 400 if user exists — that's fine)
        self.client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password},
            name="/auth/register (setup)",
        )

        # Log in to obtain a Bearer token
        resp = self.client.post(
            "/api/v1/auth/jwt/login",
            data={"username": test_email, "password": test_password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="/auth/jwt/login (setup)",
        )

        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            self.headers["Authorization"] = f"Bearer {token}"
        else:
            # If auth setup fails, tests will run without a token
            # (and correctly report 401/403 errors in the results)
            pass

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
        payload = {"message": "Hello Amadeus, what's my schedule today?", "source": "api"}
        self.client.post("/api/v1/chat", json=payload, headers=self.headers)
