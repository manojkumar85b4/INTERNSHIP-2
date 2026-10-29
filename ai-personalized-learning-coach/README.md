# 🎓 AI Personalized Learning Coach

**Xpert Champs – AI Engineering Internship Project** (Generative AI / Personalized Learning)

A Streamlit web app that builds a personalised study plan with an LLM (Gemini), quizzes the learner topic by topic,
**scores answers in Python**, flags weak topics, recommends next steps, and stores everything in SQLite.

## Features (mapped to the brief)
| Requirement | Where |
|---|---|
| FR-01 Learner setup | `app.py` → Learner Setup form, validated by `learning_plan.validate_profile` |
| FR-02/03 Plan generation, view & regenerate | `learning_plan.py`, Study Plan page, "Adjust / regenerate plan" |
| FR-04/05 Topic selection & 5-question MCQ quiz | `quiz_manager.generate_quiz`, Practice Quiz page |
| FR-06 Answer submission & correctness | `quiz_manager.score_quiz` (answer-key based) |
| FR-07 Feedback & explanations | Feedback section (explanation per question + suggested practice) |
| FR-08/09 Weak topics & recommendations | `status_for_percent`, `weak_topics`, `recommend_next` |
| FR-10 Save progress | `database.py` (SQLite) |
| FR-11 Dashboard | Progress Dashboard page |
| FR-12 Error handling | `ai_service.py`, `database.py`, friendly messages in `app.py` |

## Folder structure
```
ai-personalized-learning-coach/
├── app.py              # Streamlit UI (5 pages)
├── ai_service.py       # Gemini call, JSON extraction, retries, error classes
├── learning_plan.py    # Input validation, plan prompt, plan validation
├── quiz_manager.py     # Quiz prompt/validation, Python scoring, recommendations
├── database.py         # SQLite schema + queries
├── requirements.txt  .env.example  .gitignore  README.md
├── sample_data/example_learning_plan.json   # illustration only, not used by the app
└── tests/test_core.py  # 16 automated tests (LLM mocked)
```

## Setup
```bash
git clone <your-repo-url> && cd ai-personalized-learning-coach
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then put your GEMINI_API_KEY in .env
streamlit run app.py
```
Get a free key at https://aistudio.google.com/apikey. Never commit `.env`.

Run tests: `python -m unittest discover -s tests -v`

## How it works
1. Learner submits subject, goal, level, duration, daily minutes → validated.
2. `ai_service.generate_structured` sends a prompt, parses JSON, validates it; invalid output triggers a retry with a corrective hint (max 3 attempts), then a friendly error.
3. Plan + topics are saved to SQLite and shown.
4. Learner picks a topic → LLM returns 5 MCQs (`question, options[4], correct_answer, explanation`).
5. **Python** compares chosen options with the answer key → score. The LLM never calculates scores.
6. Attempt saved; topic status updated: `<60%` needs_revision, `60–79%` practicing, `≥80%` completed.
7. Recommendation: low → revise & retake; medium → more practice; high → next topic (with a note that one short quiz is not proof of mastery).
8. Dashboard shows completed/pending topics, scores, history and next actions.

## Prompt design
- System instruction forces JSON-only output and tells the model to treat learner text as data (basic prompt-injection guard).
- Prompts state exact counts (one topic per day, 5 questions, 4 options), level, and a JSON schema.
- `response_mime_type="application/json"` and `temperature=0.4` for predictable structure.
- Plan prompt caps `estimated_minutes` at the learner's daily time.

## Database structure
- `learners(id, subject, goal, level, duration_days, daily_minutes, created_at)`
- `plans(id, learner_id→learners, title, summary, plan_json, is_active, created_at)` – regeneration deactivates old plans
- `topics(id, plan_id→plans, day, title, objectives, estimated_minutes, activities, status, last_updated)`
- `quiz_attempts(id, plan_id, topic_id→topics, score, total, percent, questions_json, answers_json, created_at)` – every attempt is its own row

## Error handling
Missing/invalid inputs → inline messages · invalid JSON or schema → validate + retry, then error · API/key/network failure → friendly message + retry · database errors → `DatabaseError` shown in UI · no stack traces reach the learner.

## Testing (matches section 12 of the brief)
| Test case | Covered by |
|---|---|
| Missing subject/goal | `test_missing_subject_goal` |
| Valid setup → plan | `test_generate_plan_ok`, `test_valid_profile` |
| Invalid LLM response | `test_invalid_then_valid_retries`, `test_always_invalid_raises_friendly_error` |
| Score from answer key | `test_score_from_answer_key` |
| Low / high score | `test_low_score_recommends_revision`, `test_high_score_moves_forward_with_caution` |
| Persistence after restart | `test_persistence_and_repeated_attempts` |
| API failure | `test_api_failure`, `test_missing_api_key` |
| Repeated attempts | `test_persistence_and_repeated_attempts` |

## Limitations
- Quiz/plan quality depends on the LLM; answer keys could occasionally be wrong (the app only validates structure, not factual truth).
- Single-learner, no login; one active plan at a time.
- A 5-question quiz is a small sample, so "completed" means *provisionally strong*, not mastered.
- Free-tier API limits may cause temporary failures (retry works).
- Topic status uses the latest attempt only.

## Future improvements
Multi-user login, adaptive difficulty, spaced-repetition reminders, mixed-topic review quizzes, export progress to PDF.

## Viva cheat-sheet
- **Why does Python score the quiz?** LLMs can miscalculate; deterministic scoring is reliable and testable.
- **What if the model returns bad JSON?** `extract_json` strips fences, validators check fields, then retry with a corrective prompt, then a safe error.
- **Why SQLite?** Zero-setup, file-based, persists across restarts; enough for a single-user app.
- **How do you detect weak topics?** Latest quiz percent < 60% → `needs_revision`.
- **How is the API key protected?** Loaded with python-dotenv from `.env`, which is git-ignored.
