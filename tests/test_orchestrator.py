import unittest

from backend.humanproof.orchestrator import review_text


class OrchestratorTests(unittest.TestCase):
    def test_review_generates_scores_findings_and_action_plan(self):
        text = (
            "Research shows that 44 percent of people missed visits. "
            "This this sentence has a repeated word. "
            "The program was implemented by trained nurses and was reviewed by staff."
        )
        report = review_text(text, "proposal.txt")
        self.assertIn("publication_readiness", report.scores)
        self.assertTrue(report.findings)
        self.assertTrue(report.action_plan)
        categories = {finding.category for finding in report.findings}
        self.assertIn("grammar", categories)
        self.assertIn("fact_checking", categories)

    def test_ai_analysis_is_probabilistic_not_definitive(self):
        report = review_text("This is a short human-written note with varied words.", "note.txt")
        self.assertIn("ai_writing_indicator", report.scores)
        limitations = " ".join(report.limitations).lower()
        self.assertIn("probabilistic", limitations)
        self.assertIn("definitive", limitations)


if __name__ == "__main__":
    unittest.main()

