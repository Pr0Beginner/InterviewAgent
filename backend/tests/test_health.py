import unittest

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import get_settings


class HealthApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_check(self) -> None:
        response = self.client.get("/api/health", headers={"X-Request-ID": "test-id"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "test-id")
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], "0.1.0")

    def test_openapi_is_available(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/health", response.json()["paths"])

    def test_langgraph_state_path_is_absolute(self) -> None:
        self.assertTrue(get_settings().langgraph_sqlite_path.is_absolute())


if __name__ == "__main__":
    unittest.main()
