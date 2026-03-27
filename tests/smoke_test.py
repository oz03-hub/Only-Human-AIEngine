"""
Smoke tests for deployed AIEngine application.

Run against a live deployment to verify core functionality:
    python tests/smoke_test.py --url https://your-cloud-run-url --api-key YOUR_KEY

Exit code 0 = all tests passed, 1 = at least one failure.
"""

import argparse
import sys
import time

import httpx

# Unique ID so smoke test data doesn't collide across runs
RUN_ID = int(time.time()) % 100_000
group_id = 177
question_id = "884f8d90-bc63-4649-a316-2b956831dba4"

def log(label: str, passed: bool, detail: str = ""):
    icon = "PASS" if passed else "FAIL"
    msg = f"[{icon}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


class SmokeTestRunner:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.Client(timeout=timeout)
        self.failures: list[str] = []

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def _check(self, name: str, passed: bool, detail: str = ""):
        log(name, passed, detail)
        if not passed:
            self.failures.append(name)

    # ------------------------------------------------------------------
    # Individual tests
    # ------------------------------------------------------------------

    def test_root(self):
        """GET / returns app metadata."""
        r = self.client.get(f"{self.base_url}/")
        self._check(
            "root endpoint",
            r.status_code == 200 and r.json().get("status") == "running",
            f"status={r.status_code} body={r.text[:200]}",
        )

    def test_health(self):
        """GET /health returns healthy status."""
        r = self.client.get(f"{self.base_url}/health")
        ok = r.status_code == 200 and r.json().get("status") == "healthy"
        self._check("health check", ok, f"status={r.status_code} body={r.text[:200]}")

    def test_auth_rejected_without_key(self):
        """Requests without API key are rejected."""
        r = self.client.post(
            f"{self.base_url}/api/v1/messages/webhook",
            json={"payload": {"groups_metadata": [], "groups": []}},
        )
        self._check(
            "auth rejected (no key)",
            r.status_code in (401, 403),
            f"status={r.status_code}",
        )

    def test_auth_rejected_with_bad_key(self):
        """Requests with wrong API key are rejected."""
        r = self.client.post(
            f"{self.base_url}/api/v1/messages/webhook",
            json={"payload": {"groups_metadata": [], "groups": []}},
            headers={"X-API-Key": "definitely-wrong-key"},
        )
        self._check(
            "auth rejected (bad key)",
            r.status_code in (401, 403),
            f"status={r.status_code}",
        )

    def test_invalid_payload_returns_422(self):
        """Malformed payload returns 422, not 500."""
        r = self.client.post(
            f"{self.base_url}/api/v1/messages/webhook",
            json={
                "payload": {
                    "groups_metadata": [],
                    "groups": [
                        {
                            "group_id": "not-an-int",
                            "group_name": "Bad",
                            "members": [],
                            "threads": [],
                        }
                    ],
                }
            },
            headers=self._headers(),
        )
        self._check(
            "invalid payload → 422",
            r.status_code == 422,
            f"status={r.status_code}",
        )

    def test_webhook_save_and_read(self):
        """POST webhook stores data, GET logs retrieves it."""
        # group_id = 90_000 + RUN_ID
        group_id = 177
        question_id = "884f8d90-bc63-4649-a316-2b956831dba4"
        payload = {
            "payload": {
                "groups_metadata": [
                    {"group_id": group_id, "status": "active", "status_updated_at": None}
                ],
                "groups": [
                    {
                        "group_id": group_id,
                        "group_name": f"Smoke Test {RUN_ID}",
                        "members": [
                            {
                                "user_id": f"smoke-user-{RUN_ID}",
                                "first_name": "Smoke",
                                "last_name": "Tester",
                            }
                        ],
                        "threads": [
                            {
                                "question": {
                                    "id": question_id,
                                    "text": "Smoke test question",
                                    "options": [],
                                    "status": "active",
                                    "unlock_order": 1,
                                },
                                "messages": [
                                    {
                                        "user_id": f"smoke-user-{RUN_ID}",
                                        "first_name": "Smoke",
                                        "last_name": "Tester",
                                        "content": f"Smoke test message {RUN_ID}",
                                        "created_at": "2024-01-15T10:30:00Z",
                                        "is_ai": False,
                                        "is_current_member": True,
                                    }
                                ],
                                "last_ai_message_at": None,
                            }
                        ],
                    }
                ],
            }
        }

        # Store via save endpoint (no background facilitation)
        r = self.client.post(
            f"{self.base_url}/api/v1/messages/save",
            json=payload,
            headers=self._headers(),
        )
        save_ok = r.status_code == 200 and r.json().get("status") == "success"
        self._check(
            "webhook save",
            save_ok,
            f"status={r.status_code} body={r.text[:300]}",
        )

        if not save_ok:
            self._check("read back messages", False, "skipped (save failed)")
            return

        resp_data = r.json()
        self._check(
            "save response counts",
            resp_data.get("groups_affected") == 1
            and resp_data.get("messages_received") == 1,
            f"groups={resp_data.get('groups_affected')} msgs={resp_data.get('messages_received')}",
        )

        # Read back via logs
        r = self.client.get(
            f"{self.base_url}/api/v1/messages/logs",
            params={"group_id": group_id},
            headers=self._headers(),
        )
        if r.status_code == 200:
            messages = r.json()
            found = any(
                f"Smoke test message {RUN_ID}" in m.get("content", "")
                for m in messages
            )
            self._check(
                "read back messages",
                found,
                f"got {len(messages)} messages, match={'yes' if found else 'no'}",
            )
        else:
            self._check(
                "read back messages",
                False,
                f"status={r.status_code} body={r.text[:200]}",
            )

    def test_webhook_facilitation_bypass(self):
        """POST webhook with 10 messages and bypass=True triggers facilitation."""
        # group_id = 91_000 + RUN_ID
        user_id = f"smoke-fac-user-{RUN_ID}"
        group_id = 177
        question_id = "884f8d90-bc63-4649-a316-2b956831dba4"

        messages = [
            {
                "user_id": user_id,
                "first_name": "Smoke",
                "last_name": "Tester",
                "content": f"Facilitation test message {i} run {RUN_ID}",
                "created_at": f"2024-01-15T10:{i:02d}:00Z",
                "is_ai": False,
                "is_current_member": True,
            }
            for i in range(10)
        ]
        payload = {
            "bypass": True,
            "payload": {
                "groups_metadata": [
                    {"group_id": group_id, "status": "active", "status_updated_at": None}
                ],
                "groups": [
                    {
                        "group_id": group_id,
                        "group_name": f"Smoke Facilitation Test {RUN_ID}",
                        "members": [
                            {"user_id": user_id, "first_name": "Smoke", "last_name": "Tester"}
                        ],
                        "threads": [
                            {
                                "question": {
                                    "id": question_id,
                                    "text": "What are your thoughts on this topic?",
                                    "options": [],
                                    "status": "active",
                                    "unlock_order": 1,
                                },
                                "messages": messages,
                                "last_ai_message_at": None,
                            }
                        ],
                    }
                ],
            },
        }

        r = self.client.post(
            f"{self.base_url}/api/v1/messages/webhook",
            json=payload,
            headers=self._headers(),
        )
        self._check(
            "facilitation bypass webhook",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:300]}",
        )

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all smoke tests. Returns True if all passed."""
        print(f"\n{'='*60}")
        print(f"  Smoke tests — {self.base_url}")
        print(f"  Run ID: {RUN_ID}")
        print(f"{'='*60}\n")

        tests = [
            self.test_root,
            self.test_health,
            self.test_auth_rejected_without_key,
            self.test_auth_rejected_with_bad_key,
            self.test_invalid_payload_returns_422,
            self.test_webhook_save_and_read,
            self.test_webhook_facilitation_bypass,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                self._check(test.__name__, False, f"exception: {e}")

        total = len(tests)
        passed = total - len(self.failures)
        print(f"\n{'='*60}")
        print(f"  Results: {passed}/{total} passed")
        if self.failures:
            print(f"  Failed: {', '.join(self.failures)}")
        print(f"{'='*60}\n")

        return len(self.failures) == 0


def main():
    parser = argparse.ArgumentParser(description="Smoke tests for deployed AIEngine")
    parser.add_argument("--url", required=True, help="Base URL of the deployed app")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    args = parser.parse_args()

    runner = SmokeTestRunner(args.url, args.api_key, args.timeout)
    success = runner.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
