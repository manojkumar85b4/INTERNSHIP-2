"""AI Personalized Learning Coach - Streamlit UI.  Run with:  streamlit run app.py"""
import pandas as pd
import streamlit as st

import database as db
import learning_plan as lp
import quiz_manager as qm
from ai_service import AIServiceError
from database import DatabaseError

st.set_page_config(page_title="AI Personalized Learning Coach", page_icon="🎓", layout="wide")

PAGES = ["Home", "Learner Setup", "Study Plan", "Practice Quiz", "Progress Dashboard"]
STATUS_LABEL = {"pending": "⚪ Pending", "practicing": "🟡 Practicing",
                "needs_revision": "🔴 Needs revision", "completed": "🟢 Completed"}


def goto(page: str):
    st.session_state["page"] = page


def reset_quiz_state():
    for key in ("quiz", "result"):
        st.session_state.pop(key, None)


def load_plan():
    plan = db.get_active_plan()
    topics = db.get_topics(plan["id"]) if plan else []
    return plan, topics


# ---------------------------------------------------------------- pages
def page_home(plan, topics):
    st.title("🎓 AI Personalized Learning Coach")
    st.write("Tell the coach your goal, current level and available time. It builds a day-wise study plan, "
             "quizzes you topic by topic, scores your answers, spots weak areas and recommends what to study next. "
             "Everything is saved, so you can come back and continue anytime.")
    if plan:
        done = sum(t["status"] == "completed" for t in topics)
        c1, c2, c3 = st.columns(3)
        c1.metric("Current plan", plan["subject"])
        c2.metric("Topics completed", f"{done} / {len(topics)}")
        c3.metric("Needs revision", len(qm.weak_topics(topics)))
        st.button("Continue learning ➜", on_click=goto, args=("Practice Quiz",), type="primary")
    else:
        st.info("No plan yet. Open **Learner Setup** to create your first study plan.")
        st.button("Create my study plan ➜", on_click=goto, args=("Learner Setup",), type="primary")


def page_setup():
    st.header("Learner Setup")
    prev = db.get_latest_learner() or {}
    with st.form("setup_form"):
        subject = st.text_input("Subject", value=prev.get("subject", ""), placeholder="e.g. Python")
        goal = st.text_area("Learning goal", value=prev.get("goal", ""),
                            placeholder="e.g. Learn Python fundamentals well enough to write small programs")
        level = st.selectbox("Current knowledge level", lp.LEVELS,
                             index=lp.LEVELS.index(prev["level"]) if prev.get("level") in lp.LEVELS else 0)
        c1, c2 = st.columns(2)
        days = c1.number_input("Target duration (days)", 1, lp.MAX_TOPICS, int(prev.get("duration_days", 7)))
        minutes = c2.number_input("Daily study time (minutes)", 10, 600, int(prev.get("daily_minutes", 45)), step=5)
        submitted = st.form_submit_button("Generate study plan", type="primary")

    if not submitted:
        return
    profile = {"subject": subject, "goal": goal, "level": level,
               "duration_days": int(days), "daily_minutes": int(minutes)}
    errors = lp.validate_profile(profile)
    if errors:
        for e in errors:
            st.error(e)
        return
    try:
        with st.spinner("Creating your personalised plan..."):
            plan = lp.generate_plan(profile)
        plan_id = db.save_plan(db.save_learner(profile), plan)
    except AIServiceError as exc:
        st.error(f"⚠️ {exc}")
        st.info("Nothing was lost - press **Generate study plan** again to retry.")
        return
    except DatabaseError as exc:
        st.error(f"⚠️ Could not save your plan. {exc}")
        return
    reset_quiz_state()
    st.success(f"Plan created with {len(plan['topics'])} topics (plan #{plan_id}).")
    st.button("View study plan ➜", on_click=goto, args=("Study Plan",))


def page_plan(plan, topics):
    st.header("Study Plan")
    if not plan:
        st.info("No plan yet - create one in **Learner Setup**.")
        return
    st.subheader(plan["title"])
    st.caption(f"{plan['subject']} • {plan['level']} • {plan['duration_days']} days • "
               f"{plan['daily_minutes']} min/day")
    if plan["summary"]:
        st.write(plan["summary"])
    for t in topics:
        with st.expander(f"Day {t['day']}: {t['title']}  —  {STATUS_LABEL[t['status']]}  "
                         f"({t['estimated_minutes']} min)"):
            st.markdown("**Objectives**")
            for o in t["objectives"]:
                st.markdown(f"- {o}")
            st.markdown("**Practice activities**")
            for a in t["activities"]:
                st.markdown(f"- {a}")
    st.divider()
    st.write("Goal or schedule changed? Regenerate the plan with new details.")
    st.button("Adjust / regenerate plan", on_click=goto, args=("Learner Setup",))


def render_result(result, topic):
    st.subheader("Feedback")
    scored = result["scored"]
    c1, c2 = st.columns(2)
    c1.metric("Score", f"{scored['score']} / {scored['total']}")
    c2.metric("Percentage", f"{scored['percent']:.0f}%")
    rec = result["recommendation"]
    if rec["action"] == "revise":
        st.error("📌 " + rec["message"])
    elif rec["action"] == "practice":
        st.warning("📌 " + rec["message"])
    else:
        st.success("📌 " + rec["message"])
    for i, (q, r) in enumerate(zip(result["questions"], scored["results"]), start=1):
        icon = "✅" if r["correct"] else "❌"
        st.markdown(f"**{icon} Q{i}. {q['question']}**")
        chosen = "No answer" if r["chosen"] is None else f"{qm.LETTERS[r['chosen']]}. {q['options'][r['chosen']]}"
        st.write(f"Your answer: {chosen}")
        if not r["correct"]:
            st.write(f"Correct answer: {qm.LETTERS[r['correct_index']]}. {q['options'][r['correct_index']]}")
        st.caption(f"💡 {r['explanation']}")
    wrong = [i for i, r in enumerate(scored["results"], start=1) if not r["correct"]]
    if wrong:
        st.info("Suggested practice: revisit " + "; ".join(topic["activities"][:2]) +
                f". Focus on questions {', '.join('Q' + str(n) for n in wrong)}.")
    b1, b2 = st.columns(2)
    if b1.button("Retake same quiz"):
        quiz = st.session_state["quiz"]
        quiz["nonce"] += 1
        st.session_state.pop("result", None)
        st.rerun()
    if b2.button("Generate a new quiz"):
        reset_quiz_state()
        st.rerun()


def page_quiz(plan, topics):
    st.header("Practice Quiz")
    if not plan:
        st.info("Create a study plan first in **Learner Setup**.")
        return
    nxt = qm.pick_next_topic(topics)
    default_idx = topics.index(nxt) if nxt in topics else 0
    topic = st.selectbox("Choose a topic", topics, index=default_idx,
                         format_func=lambda t: f"Day {t['day']}: {t['title']} — {STATUS_LABEL[t['status']]}")
    quiz = st.session_state.get("quiz")
    if quiz and quiz["topic_id"] != topic["id"]:
        reset_quiz_state()
        quiz = None

    if st.button("Generate quiz", type="primary"):
        try:
            with st.spinner("Preparing your quiz..."):
                questions = qm.generate_quiz(topic, plan["level"], plan["subject"])
        except AIServiceError as exc:
            st.error(f"⚠️ {exc}")
            st.info("Press **Generate quiz** to try again.")
            return
        st.session_state["quiz"] = {"topic_id": topic["id"], "questions": questions, "nonce": 0}
        st.session_state.pop("result", None)
        st.rerun()

    quiz = st.session_state.get("quiz")
    if not quiz:
        st.caption("Pick a topic and generate a short 5-question quiz.")
        return

    if "result" in st.session_state:
        render_result(st.session_state["result"], topic)
        return

    with st.form(f"quiz_form_{quiz['nonce']}"):
        answers = []
        for i, q in enumerate(quiz["questions"]):
            st.markdown(f"**Q{i + 1}. {q['question']}**")
            answers.append(st.radio(
                f"Answer for question {i + 1}", options=list(range(4)), index=None,
                format_func=lambda x, q=q: f"{qm.LETTERS[x]}. {q['options'][x]}",
                key=f"q{quiz['nonce']}_{i}", label_visibility="collapsed"))
        submitted = st.form_submit_button("Submit answers", type="primary")

    if not submitted:
        return
    if any(a is None for a in answers):
        st.warning("Please answer every question before submitting.")
        return
    scored = qm.score_quiz(quiz["questions"], answers)  # Python scores it, not the LLM
    try:
        db.save_attempt(plan["id"], topic["id"], scored["score"], scored["total"], scored["percent"],
                        quiz["questions"], answers)
        db.update_topic_status(topic["id"], qm.status_for_percent(scored["percent"]))
        topics = db.get_topics(plan["id"])
        attempts = len(db.get_attempts(plan["id"], topic["id"]))
    except DatabaseError as exc:
        st.error(f"⚠️ Could not save your attempt. {exc}")
        return
    rec = qm.recommend_next(topic, scored["percent"], topics, attempts)
    st.session_state["result"] = {"scored": scored, "questions": quiz["questions"], "recommendation": rec}
    st.rerun()


def page_dashboard(plan, topics):
    st.header("Progress Dashboard")
    if not plan:
        st.info("No progress yet - create a plan and take a quiz.")
        return
    attempts = db.get_attempts(plan["id"], limit=100)
    done = sum(t["status"] == "completed" for t in topics)
    avg = round(sum(a["percent"] for a in attempts) / len(attempts), 1) if attempts else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completed", f"{done} / {len(topics)}")
    c2.metric("Pending", sum(t["status"] == "pending" for t in topics))
    c3.metric("Needs revision", len(qm.weak_topics(topics)))
    c4.metric("Average score", f"{avg}%" if avg is not None else "—")
    st.progress(done / len(topics) if topics else 0.0, text="Overall progress")

    st.subheader("Next actions")
    weak = qm.weak_topics(topics)
    nxt = qm.pick_next_topic(topics)
    for t in weak:
        st.error(f"Revise **Day {t['day']}: {t['title']}** and retake its quiz.")
    if nxt and nxt not in weak:
        st.success(f"Continue with **Day {nxt['day']}: {nxt['title']}**.")
    if not weak and not nxt:
        st.success("All topics are done - try harder practice or a final review quiz.")

    st.subheader("Topics")
    st.dataframe(pd.DataFrame([{"Day": t["day"], "Topic": t["title"], "Status": STATUS_LABEL[t["status"]],
                                "Minutes": t["estimated_minutes"]} for t in topics]),
                 hide_index=True, use_container_width=True)

    st.subheader("Quiz history")
    if not attempts:
        st.caption("No quiz attempts yet.")
        return
    hist = pd.DataFrame([{"When": a["created_at"].replace("T", " "), "Topic": f"Day {a['day']}: {a['topic_title']}",
                          "Score": f"{a['score']}/{a['total']}", "Percent": a["percent"]} for a in attempts])
    st.dataframe(hist, hide_index=True, use_container_width=True)
    st.caption("Recent scores (oldest → newest)")
    st.line_chart(pd.DataFrame({"Percent": [a["percent"] for a in reversed(attempts[:15])]}))


# ---------------------------------------------------------------- main
def main():
    try:
        db.init_db()
        plan, topics = load_plan()
    except DatabaseError as exc:
        st.error(f"⚠️ {exc}")
        st.stop()
    if "page" not in st.session_state:
        st.session_state["page"] = "Home"
    st.sidebar.title("🎓 Learning Coach")
    st.sidebar.radio("Navigate", PAGES, key="page")
    page = st.session_state["page"]
    try:
        if page == "Home":
            page_home(plan, topics)
        elif page == "Learner Setup":
            page_setup()
        elif page == "Study Plan":
            page_plan(plan, topics)
        elif page == "Practice Quiz":
            page_quiz(plan, topics)
        else:
            page_dashboard(plan, topics)
    except DatabaseError as exc:
        st.error(f"⚠️ {exc}")


main()
