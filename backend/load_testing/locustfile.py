import logging
import subprocess

from locust import FastHttpUser, between, tag, task


def get_gcloud_identity_token() -> str:
    """Return a Google Cloud identity token using gcloud CLI.

    If the command fails (e.g., gcloud not installed or not authenticated),
    we fall back to an empty string so tests still run (though auth may fail).
    """
    cmd = ["gcloud", "auth", "print-identity-token"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as exc:
        # Avoid raising to keep load test usable without gcloud.
        logging.warning("Could not obtain identity token: %s", exc)
        return ""


SHARED_BEARER_TOKEN = get_gcloud_identity_token()

AUTH_HEADERS = (
    {"Authorization": f"Bearer {SHARED_BEARER_TOKEN}"} if SHARED_BEARER_TOKEN else {}
)


class HealthcheckUser(FastHttpUser):
    """Continuously hits the healthcheck for baseline latency."""

    wait_time = between(0.2, 1)
    weight = 1  # Lower weight so CRUD users dominate when users > 1

    @tag("healthcheck")
    @task
    def healthcheck(self):
        self.client.get("/healthcheck", headers=AUTH_HEADERS)


class SampleCrudUser(FastHttpUser):
    """Exercises deterministic CRUD lifecycle for /api/samples endpoints.

    Each simulated user:
        1. Creates one sample at startup (bootstraps `sample_ids`).
        2. Lists paginated samples (weighted list task).
        3. Retrieves the first stored sample (if any).
        4. Applies a fixed price update to that first sample.
        5. Deletes the first sample only after at least 3 are accumulated (keeps a small pool).

    Notes:
        * Authorization header added if an identity token is available.
        * Deterministic IDs selection + fixed prices give reproducible latency patterns.
        * Adjust task weights (@task decorator numbers) to shape traffic mix.
    """

    wait_time = between(0.2, 1)
    weight = 3  # Higher weight so this class spawns earlier/more often
    sample_ids: list[str] = []

    # Helper methods -------------------------------------------------
    def _create_sample(self) -> str | None:
        payload = {
            "name": "Name",
            "description": "Load test entity",
            "price": 10.0,
            "is_active": True,
        }
        with self.client.post(
            "/api/samples/", json=payload, headers=AUTH_HEADERS, catch_response=True
        ) as resp:
            if resp.status_code == 201:
                sample_id = resp.json()["id"]
                self.sample_ids.append(sample_id)
                return sample_id
            else:
                resp.failure(f"Create failed: {resp.status_code} {resp.text}")
        return None

    # Task methods ---------------------------------------------------
    @tag("list_samples")
    @task(2)
    def list_samples(self):
        self.client.get("/api/samples/?page=1&size=10", headers=AUTH_HEADERS)

    @tag("create_sample")
    @task(1)
    def create_sample(self):
        self._create_sample()
