"""Application skill packaging and loading contract tests."""

from pathlib import Path
import unittest

from backend.app.agent.skills import load_skill


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "app" / "agent" / "skills"


class SkillPackagingTest(unittest.TestCase):
    def test_packaged_skills_use_standard_entrypoints(self):
        for name in ("mock-interview", "job-recommendation"):
            with self.subTest(skill=name):
                self.assertTrue((SKILLS_ROOT / name / "SKILL.md").is_file())
                instructions = load_skill(name)
                self.assertTrue(instructions)
                self.assertFalse(instructions.startswith("---"))

    def test_loader_rejects_non_canonical_skill_names(self):
        for name in ("mock_interview", "../mock-interview", "Mock-Interview"):
            with self.subTest(skill=name), self.assertRaises(ValueError):
                load_skill(name)


if __name__ == "__main__":
    unittest.main()
