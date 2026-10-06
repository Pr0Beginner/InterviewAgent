"""BOSS 搜索计划、URL 安全边界和 HTML 解析测试。"""

import unittest

from backend.app.integrations.boss import (
    BossSearchPlan,
    build_search_plans,
    build_search_url,
    canonical_job_url,
    extract_job_description,
    matches_work_experience,
    normalize_listing,
    valid_job_url,
)


class BossSourceTest(unittest.TestCase):
    def test_search_plans_follow_city_keyword_page_order_and_cap(self):
        plans = build_search_plans(
            ["Java", "后端", "Java"],
            ["杭州", "上海"],
            pages_per_query=2,
            max_plans=5,
        )
        self.assertEqual(
            [(plan.city, plan.keyword, plan.page) for plan in plans],
            [
                ("杭州", "Java", 1),
                ("杭州", "Java", 2),
                ("杭州", "后端", 1),
                ("杭州", "后端", 2),
                ("上海", "Java", 1),
            ],
        )
        self.assertTrue(all(plan.work_experience == "应届生" for plan in plans))

    def test_search_url_uses_known_city_code_and_encodes_unknown_city(self):
        known = build_search_url(BossSearchPlan("Java 后端", "杭州", 2, "不限"))
        unknown = build_search_url(BossSearchPlan("Java", "海外", 1, "不限"))
        self.assertIn("/c101210100/?", known)
        self.assertIn("query=Java+%E5%90%8E%E7%AB%AF", known)
        self.assertIn("page=2", known)
        self.assertIn("/c100010000/?", unknown)
        self.assertIn("query=Java+%E6%B5%B7%E5%A4%96", unknown)

    def test_search_url_and_listing_filter_include_work_experience(self):
        url = build_search_url(BossSearchPlan("Java 后端", "广州", 1, "应届生"))
        self.assertIn("query=Java+%E5%90%8E%E7%AB%AF+%E5%BA%94%E5%B1%8A%E7%94%9F", url)
        self.assertTrue(matches_work_experience({
            "position_name": "Java 开发",
            "list_summary": "广州 在校/应届 本科",
        }, "应届生"))
        self.assertFalse(matches_work_experience({
            "position_name": "Java 技术专家",
            "list_summary": "广州 3-5年 本科",
        }, "应届生"))
        self.assertTrue(matches_work_experience({"list_summary": "广州 3-5年"}, "不限"))

    def test_listing_normalization_rejects_external_url_and_keeps_metadata(self):
        plan = BossSearchPlan("Java", "深圳", 1)
        self.assertIsNone(normalize_listing({"href": "https://evil.example/job_detail/1.html"}, plan))
        listing = normalize_listing({
            "href": "https://www.zhipin.com/job_detail/abc123.html?ka=search_list_1",
            "title": " Java 后端 ",
            "company": " 测试公司 ",
            "salary": "20-30K",
            "location": "深圳·南山",
            "summary": "Java 后端   20-30K",
        }, plan)
        self.assertEqual(listing["job_id"], "abc123")
        self.assertEqual(listing["company_name"], "测试公司")
        self.assertEqual(listing["list_summary"], "Java 后端 20-30K")
        self.assertEqual(listing["job_url"], "https://www.zhipin.com/job_detail/abc123.html")
        self.assertTrue(valid_job_url(listing["job_url"]))
        self.assertEqual(
            canonical_job_url("/job_detail/abc123.html?ka=search_list_2#top"),
            "https://www.zhipin.com/job_detail/abc123.html",
        )

    def test_listing_ignores_obfuscated_salary_until_detail_page(self):
        listing = normalize_listing({
            "href": "/job_detail/abc123.html",
            "title": "Java 后端",
            "company": "测试公司",
            "salary": "\ue035-\ue037K",
            "location": "杭州",
            "summary": "Java 后端 \ue035-\ue037K 测试公司",
        }, BossSearchPlan("Java", "杭州", 1))
        self.assertEqual(listing["salary"], "")
        self.assertNotRegex(listing["list_summary"], "[\ue000-\uf8ff]")

    def test_listing_recovers_district_from_summary(self):
        listing = normalize_listing({
            "href": "/job_detail/abc123.html",
            "title": "Java 后端",
            "summary": "Java 后端 测试公司杭州·拱墅区",
        }, BossSearchPlan("Java", "杭州", 1))
        self.assertEqual(listing["base_location"], "杭州·拱墅区")

    def test_detail_parser_prefers_job_section_and_rejects_unconfirmed_page(self):
        html = """
        <html><body><nav>导航噪声</nav><h1>Java 后端</h1>
        <section class="job-sec-text"><h3>职位描述</h3><p>负责服务端开发。</p>
        <h3>任职要求</h3><p>熟悉 Java 与 MySQL。</p></section>
        <footer>页脚噪声</footer></body></html>
        """
        description = extract_job_description(html)
        self.assertIn("负责服务端开发", description)
        self.assertIn("熟悉 Java 与 MySQL", description)
        self.assertNotIn("导航噪声", description)
        self.assertEqual(extract_job_description("<html><body>普通页面</body></html>"), "")

    def test_detail_parser_normalizes_short_responsibility_heading(self):
        html = """<section class="job-sec-text"><p>岗位职</p><p>boss</p><p>责:</p><p>开发后台服务。</p>
        <p>直聘</p><p>任职要求：</p><p>熟悉 Java。</p></section>"""
        description = extract_job_description(html)
        self.assertIn("岗位职责：", description)
        self.assertNotIn("BOSS直聘", description)

    def test_detail_parser_normalizes_main_responsibilities_heading(self):
        html = """<section class="job-sec-text"><p>主要职责</p><p>开发后台服务。</p>
        <p>任职要求：</p><p>熟悉 Java。</p></section>"""
        self.assertIn("岗位职责：", extract_job_description(html))


if __name__ == "__main__":
    unittest.main()
