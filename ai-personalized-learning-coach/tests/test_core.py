import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import ai_service
import database as db
import learning_plan as lp
import quiz_manager as qm

ai_service.RETRY_DELAY_SECONDS = 0

PROFILE = {"subject": "Python", "goal": "Learn basics", "level": "Beginner", "duration_days": 2, "daily_minutes": 45}
PLAN_JSON = {"title": "T", "summary": "S", "topics": [
    {"day": 1, "title": "Variables", "objectives": ["a"], "estimated_minutes": 45, "activities": ["x"]},
    {"day": 2, "title": "Loops", "objectives": ["b"], "estimated_minutes": 45, "activities": ["y"]}]}


def quiz_json(n=5):
    return {"questions": [{"question": f"Q{i}?", "options": ["a", "b", "c", "d"],
                           "correct_answer": "B", "explanation": "because"} for i in range(n)]}


class TestValidation(unittest.TestCase):
    def test_missing_subject_goal(self):
        errs = lp.validate_profile({**PROFILE, "subject": " ", "goal": ""})
        self.assertEqual(len(errs), 2)

    def test_valid_profile(self):
        self.assertEqual(lp.validate_profile(PROFILE), [])

    def test_plan_validation(self):
        self.assertEqual(len(lp.validate_plan(PLAN_JSON)["topics"]), 2)
        with self.assertRaises(ValueError):
            lp.validate_plan({"topics": []})
        with self.assertRaises(ValueError):
            lp.validate_plan({"topics": [{"title": "x", "objectives": ["a"], "estimated_minutes": "abc", "activities": ["z"]}]})

    def test_quiz_validation(self):
        self.assertEqual(len(qm.validate_quiz(quiz_json())), 5)
        bad = quiz_json()
        bad["questions"][0]["correct_answer"] = "Z"
        with self.assertRaises(ValueError):
            qm.validate_quiz(bad)
        with self.assertRaises(ValueError):
            qm.validate_quiz(quiz_json(3))

    def test_extract_json_fences(self):
        self.assertEqual(ai_service.extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(ai_service.InvalidResponseError):
            ai_service.extract_json("not json")


class TestScoringAndRecommendations(unittest.TestCase):
    def setUp(self):
        self.qs = qm.validate_quiz(quiz_json())  # correct index is 1 for all
        self.topics = [{"id": 1, "day": 1, "title": "Loops", "status": "pending"},
                       {"id": 2, "day": 2, "title": "Lists", "status": "pending"}]

    def test_score_from_answer_key(self):
        r = qm.score_quiz(self.qs, [1, 1, 0, 0, None])
        self.assertEqual((r["score"], r["total"], r["percent"]), (2, 5, 40.0))

    def test_low_score_recommends_revision(self):
        rec = qm.recommend_next(self.topics[0], 40, self.topics, 1)
        self.assertEqual(rec["action"], "revise")
        self.assertEqual(qm.status_for_percent(40), "needs_revision")

    def test_high_score_moves_forward_with_caution(self):
        rec = qm.recommend_next(self.topics[0], 100, self.topics, 1)
        self.assertEqual(rec["action"], "advance")
        self.assertEqual(rec["next_topic_id"], 2)
        self.assertIn("not proof of mastery", rec["message"])

    def test_high_score_no_topics_left(self):
        for t in self.topics:
            t["status"] = "completed"
        self.assertEqual(qm.recommend_next(self.topics[0], 100, self.topics, 3)["action"], "harder")


class TestLLMFlow(unittest.TestCase):
    def test_generate_plan_ok(self):
        with mock.patch("ai_service.call_llm", return_value=json.dumps(PLAN_JSON)):
            self.assertEqual(lp.generate_plan(PROFILE)["title"], "T")

    def test_invalid_then_valid_retries(self):
        with mock.patch("ai_service.call_llm", side_effect=["garbage", json.dumps(PLAN_JSON)]) as m:
            lp.generate_plan(PROFILE)
            self.assertEqual(m.call_count, 2)

    def test_always_invalid_raises_friendly_error(self):
        with mock.patch("ai_service.call_llm", return_value="garbage"):
            with self.assertRaises(ai_service.AIServiceError):
                lp.generate_plan(PROFILE)

    def test_api_failure(self):
        with mock.patch("ai_service.call_llm", side_effect=ai_service.AIServiceError("down")):
            with self.assertRaises(ai_service.AIServiceError):
                qm.generate_quiz({"title": "t", "objectives": ["o"]}, "Beginner", "Python")

    def test_missing_api_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaises(ai_service.AIServiceError):
                ai_service.call_llm("hi")


class TestDatabase(unittest.TestCase):
    def test_persistence_and_repeated_attempts(self):
        db.init_db()
        pid = db.save_plan(db.save_learner(PROFILE), lp.validate_plan(PLAN_JSON))
        topics = db.get_topics(pid)
        tid = topics[0]["id"]
        db.save_attempt(pid, tid, 2, 5, 40.0, [], [0])
        db.save_attempt(pid, tid, 4, 5, 80.0, [], [1])
        db.update_topic_status(tid, "needs_revision")
        db.init_db()  # simulates app restart (same file)
        plan = db.get_active_plan()
        self.assertEqual(plan["id"], pid)
        self.assertEqual(len(db.get_attempts(pid, tid)), 2)
        self.assertEqual(db.get_topics(pid)[0]["status"], "needs_revision")

    def test_regeneration_deactivates_old_plan(self):
        db.init_db()
        lid = db.save_learner(PROFILE)
        db.save_plan(lid, lp.validate_plan(PLAN_JSON))
        new_id = db.save_plan(lid, lp.validate_plan(PLAN_JSON))
        self.assertEqual(db.get_active_plan()["id"], new_id)


if __name__ == "__main__":
    unittest.main()
