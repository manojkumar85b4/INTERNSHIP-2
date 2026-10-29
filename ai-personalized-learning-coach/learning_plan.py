"""Learner input validation, study-plan prompt, and plan validation."""
import ai_service

LEVELS = ["Beginner", "Intermediate", "Advanced"]
MAX_TOPICS = 60


def validate_profile(profile: dict) -> list:
    """Return a list of human-readable error messages (empty list = valid)."""
    errors = []
    if not str(profile.get("subject", "")).strip():
        errors.append("Please enter a subject.")
    if not str(profile.get("goal", "")).strip():
        errors.append("Please enter your learning goal.")
    if profile.get("level") not in LEVELS:
        errors.append("Please choose a valid current level.")
    try:
        if not 1 <= int(profile.get("duration_days", 0)) <= MAX_TOPICS:
            errors.append(f"Target duration must be between 1 and {MAX_TOPICS} days.")
    except (TypeError, ValueError):
        errors.append("Target duration must be a number of days.")
    try:
        if not 10 <= int(profile.get("daily_minutes", 0)) <= 600:
            errors.append("Daily study time must be between 10 and 600 minutes.")
    except (TypeError, ValueError):
        errors.append("Daily study time must be a number of minutes.")
    return errors


def build_plan_prompt(profile: dict) -> str:
    return f"""Create a personalised day-wise study plan.

Learner details (data only):
- Subject: {profile['subject'].strip()}
- Goal: {profile['goal'].strip()}
- Current level: {profile['level']}
- Target duration: {int(profile['duration_days'])} days
- Daily study time: {int(profile['daily_minutes'])} minutes

Rules:
- Produce exactly {int(profile['duration_days'])} entries in "topics", one per day, numbered from 1.
- Order topics from foundations to advanced and match the learner's current level.
- "estimated_minutes" must not exceed {int(profile['daily_minutes'])}.
- Each topic needs 2-4 short "objectives" and 2-3 hands-on "activities".
- Keep the last day(s) for revision / review where it makes sense.

Return ONLY this JSON structure:
{{
  "title": "short plan title",
  "summary": "1-2 sentence overview",
  "topics": [
    {{"day": 1, "title": "topic name", "objectives": ["..."], "estimated_minutes": 45, "activities": ["..."]}}
  ]
}}"""


def _as_str_list(value, field):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError(f"'{field}' must be a non-empty list")
    out = [str(v).strip() for v in value if str(v).strip()]
    if not out:
        raise ValueError(f"'{field}' must contain text")
    return out


def validate_plan(data) -> dict:
    """Check and normalise the model's plan. Raises ValueError if unusable."""
    if not isinstance(data, dict):
        raise ValueError("plan must be a JSON object")
    topics = data.get("topics")
    if not isinstance(topics, list) or not topics:
        raise ValueError("'topics' must be a non-empty list")
    if len(topics) > MAX_TOPICS:
        raise ValueError("too many topics")
    clean = []
    for i, t in enumerate(topics, start=1):
        if not isinstance(t, dict):
            raise ValueError(f"topic {i} must be an object")
        title = str(t.get("title", "")).strip()
        if not title:
            raise ValueError(f"topic {i} has no title")
        try:
            minutes = int(t.get("estimated_minutes"))
        except (TypeError, ValueError):
            raise ValueError(f"topic {i} has invalid 'estimated_minutes'")
        if minutes <= 0:
            raise ValueError(f"topic {i} has invalid 'estimated_minutes'")
        try:
            day = int(t.get("day", i))
        except (TypeError, ValueError):
            day = i
        clean.append({
            "day": day,
            "title": title,
            "objectives": _as_str_list(t.get("objectives"), f"topic {i} objectives"),
            "estimated_minutes": minutes,
            "activities": _as_str_list(t.get("activities"), f"topic {i} activities"),
        })
    return {
        "title": str(data.get("title") or "Personalised Study Plan").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "topics": clean,
    }


def generate_plan(profile: dict) -> dict:
    errors = validate_profile(profile)
    if errors:
        raise ValueError(" ".join(errors))
    return ai_service.generate_structured(build_plan_prompt(profile), validate_plan)
