"""Quiz generation, validation, Python-side scoring, weak-topic detection, recommendations.

IMPORTANT: scores are computed here from the answer key - never by the LLM.
"""
import ai_service

NUM_QUESTIONS = 5
LETTERS = ["A", "B", "C", "D"]
WEAK_THRESHOLD = 60    # below this percent -> needs revision
STRONG_THRESHOLD = 80  # at/above this percent -> strong (provisional)


def build_quiz_prompt(topic: dict, level: str, subject: str, n: int = NUM_QUESTIONS) -> str:
    objectives = "; ".join(topic["objectives"])
    return f"""Create a practice quiz of exactly {n} multiple-choice questions.

Subject: {subject}
Topic: {topic['title']}
Learning objectives: {objectives}
Learner level: {level}

Rules:
- Each question has exactly 4 distinct options and exactly one correct option.
- Difficulty and explanation wording must suit a {level} learner.
- "correct_answer" is the letter A, B, C or D matching the correct option.
- "explanation" briefly says why the answer is correct (1-2 sentences).
- Do not repeat questions. Vary what you test within the topic.

Return ONLY this JSON structure:
{{
  "questions": [
    {{"question": "...", "options": ["...", "...", "...", "..."], "correct_answer": "B", "explanation": "..."}}
  ]
}}"""


def validate_quiz(data, n: int = NUM_QUESTIONS) -> list:
    """Normalise to [{question, options, correct_index, explanation}]. Raises ValueError if bad."""
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError("'questions' list missing")
    raw = data["questions"]
    if len(raw) < n:
        raise ValueError(f"expected {n} questions but got {len(raw)}")
    questions = []
    for i, q in enumerate(raw[:n], start=1):
        if not isinstance(q, dict):
            raise ValueError(f"question {i} must be an object")
        text = str(q.get("question", "")).strip()
        options = q.get("options")
        if not text:
            raise ValueError(f"question {i} has no text")
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"question {i} must have exactly 4 options")
        options = [str(o).strip() for o in options]
        if any(not o for o in options) or len(set(o.lower() for o in options)) != 4:
            raise ValueError(f"question {i} options must be non-empty and distinct")
        answer = str(q.get("correct_answer", "")).strip().upper()[:1]
        if answer not in LETTERS:
            raise ValueError(f"question {i} has invalid 'correct_answer'")
        questions.append({
            "question": text,
            "options": options,
            "correct_index": LETTERS.index(answer),
            "explanation": str(q.get("explanation", "")).strip() or "No explanation provided.",
        })
    return questions


def generate_quiz(topic: dict, level: str, subject: str) -> list:
    prompt = build_quiz_prompt(topic, level, subject)
    return ai_service.generate_structured(prompt, validate_quiz)


def score_quiz(questions: list, answers: list) -> dict:
    """Score using the answer key. answers[i] is the chosen option index (or None)."""
    results, score = [], 0
    for q, chosen in zip(questions, answers):
        correct = chosen is not None and chosen == q["correct_index"]
        score += int(correct)
        results.append({"correct": correct, "chosen": chosen, "correct_index": q["correct_index"],
                        "explanation": q["explanation"]})
    total = len(questions)
    percent = round(100 * score / total, 1) if total else 0.0
    return {"score": score, "total": total, "percent": percent, "results": results}


def status_for_percent(percent: float) -> str:
    if percent < WEAK_THRESHOLD:
        return "needs_revision"
    if percent < STRONG_THRESHOLD:
        return "practicing"
    return "completed"


def pick_next_topic(topics: list, exclude_id=None):
    """First topic needing revision, otherwise the first pending/practicing topic."""
    candidates = [t for t in topics if t["id"] != exclude_id]
    for t in candidates:
        if t["status"] == "needs_revision":
            return t
    for t in candidates:
        if t["status"] in ("pending", "practicing"):
            return t
    return None


def weak_topics(topics: list) -> list:
    return [t for t in topics if t["status"] == "needs_revision"]


def recommend_next(topic: dict, percent: float, topics: list, attempts_on_topic: int) -> dict:
    """Return {action, message, next_topic_id} based on the latest score."""
    if percent < WEAK_THRESHOLD:
        return {"action": "revise", "next_topic_id": topic["id"],
                "message": (f"You scored {percent:.0f}% on '{topic['title']}', so it is flagged for revision. "
                            "Review the objectives and activities, then take another practice quiz.")}
    if percent < STRONG_THRESHOLD:
        return {"action": "practice", "next_topic_id": topic["id"],
                "message": (f"You scored {percent:.0f}% on '{topic['title']}'. You are getting there - "
                            "do a little more practice on this topic before moving on.")}
    nxt = pick_next_topic(topics, exclude_id=topic["id"])
    caution = ""
    if attempts_on_topic < 2:
        caution = (" One short quiz is a small sample, so treat this as a good sign, not proof of mastery - "
                   "revisit it briefly later.")
    if nxt:
        return {"action": "advance", "next_topic_id": nxt["id"],
                "message": f"Strong result ({percent:.0f}%). Next up: Day {nxt['day']} - {nxt['title']}." + caution}
    return {"action": "harder", "next_topic_id": topic["id"],
            "message": (f"Strong result ({percent:.0f}%) and no pending topics are left. "
                        "Try harder practice or a mixed review quiz." + caution)}
