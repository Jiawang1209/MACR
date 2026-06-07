from macr.discuss_roles import (
    CONSENSUS,
    DISCUSS_PLANNER,
    DISCUSS_TURN,
    render_transcript,
)
from macr.schemas import ConsensusPlan, DiscussionTurn, MessageType, PlannerOutput, SharedState


def test_role_wiring():
    assert DISCUSS_PLANNER.content_model is PlannerOutput
    assert DISCUSS_TURN.content_model is DiscussionTurn
    assert CONSENSUS.content_model is ConsensusPlan
    assert CONSENSUS.message_type is MessageType.DECISION


def test_planner_user_has_topic_only():
    s = SharedState(run_id="R1", user_query="t", topic="build a parser")
    s.discussion.append({"round": 0, "agent": "claude", "kind": "plan",
                         "content": {"summary": "secret", "steps": ["x"]}})
    user = DISCUSS_PLANNER.build_user(s)
    assert "build a parser" in user
    assert "secret" not in user  # planner is independent; does not see transcript


def test_turn_user_has_topic_and_transcript():
    s = SharedState(run_id="R1", user_query="t", topic="topic-z")
    s.discussion.append({"round": 0, "agent": "codex", "kind": "plan",
                         "content": {"summary": "plan-b", "steps": ["step-b"]}})
    user = DISCUSS_TURN.build_user(s)
    assert "topic-z" in user and "plan-b" in user and "step-b" in user


def test_turn_user_includes_human_interjection():
    s = SharedState(run_id="R1", user_query="t", topic="z")
    s.discussion.append({"round": 1, "agent": "human", "kind": "interjection",
                         "content": "please prioritize zero downtime"})
    assert "zero downtime" in DISCUSS_TURN.build_user(s)


def test_render_transcript_orders_and_renders_kinds():
    disc = [
        {"round": 0, "agent": "claude", "kind": "plan", "content": {"summary": "s", "steps": ["a"]}},
        {"round": 1, "agent": "codex", "kind": "turn",
         "content": {"response": "r", "agreements": ["x"], "concerns": ["y"], "revised_steps": ["z"]}},
        {"round": 1, "agent": "human", "kind": "interjection", "content": "hi"},
    ]
    text = render_transcript(disc)
    assert "claude" in text and "codex" in text and "human" in text
    assert "a" in text and "r" in text and "hi" in text
