import json
import unittest

import httpx

from client.api.hybrid_api import ApiRequestError, HybridApiClient


class HybridApiClientTest(unittest.TestCase):
    def test_interview_list_uses_backend_and_omits_all_status(self) -> None:
        captured_request: httpx.Request | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                200,
                json={
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "page_size": 6,
                    "total_pages": 1,
                    "has_previous": False,
                    "has_next": False,
                    "summary": {"total": 0, "status_counts": {}},
                },
            )

        api = HybridApiClient(
            base_url="http://testserver/api",
            transport=httpx.MockTransport(handler),
        )
        try:
            result = api.list_interviews(status="全部", page=1, page_size=6)
        finally:
            api.close()

        self.assertEqual(result["total"], 0)
        assert captured_request is not None
        self.assertEqual(captured_request.url.path, "/api/interviews")
        self.assertNotIn("status", captured_request.url.params)

    def test_row_update_sends_iso_dates_and_extensions(self) -> None:
        captured_body: dict | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "company_name": "网易",
                    "position_name": "Java 后端开发工程师",
                    "base_location": "杭州",
                    "current_status": "二面",
                    "interview_time": "2026-10-08T14:00:00",
                    "interview_end_time": "2026-10-08T15:00:00",
                    "job_url": None,
                    "updated_at": "2026-09-30T16:00:00",
                    "feishu_sync_status": "pending",
                },
            )

        api = HybridApiClient(
            base_url="http://testserver/api",
            transport=httpx.MockTransport(handler),
        )
        try:
            api.update_interview(
                interview_id=7,
                company_name="网易",
                position_name="Java 后端开发工程师",
                base_location="杭州",
                current_status="二面",
                interview_time="2026-10-08 14:00",
                interview_end_time="2026-10-08 15:00",
                extensions={"source": "editable_table"},
            )
        finally:
            api.close()

        assert captured_body is not None
        self.assertEqual(captured_body["interview_time"], "2026-10-08T14:00")
        self.assertEqual(captured_body["interview_end_time"], "2026-10-08T15:00")
        self.assertNotIn("updated_at", captured_body)
        self.assertEqual(captured_body["extensions"]["source"], "editable_table")

    def test_backend_error_is_user_readable(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={"error": {"message": "投递记录不存在"}},
            )

        api = HybridApiClient(
            base_url="http://testserver/api",
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaisesRegex(ApiRequestError, "投递记录不存在"):
                api.update_interview_status(999, "已结束")
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main()
