from __future__ import annotations

from macr.roles import RoleSpec
from macr.schemas import (
    ConsensusPlan,
    DiscussionTurn,
    MessageType,
    PlannerOutput,
    SharedState,
)


def render_transcript(discussion: list[dict]) -> str:
    """Render the ordered discussion records into human-readable text."""
    blocks: list[str] = []
    for e in discussion:
        head = f"[round {e.get('round')} · {e.get('agent')} · {e.get('kind')}]"
        content = e.get("content")
        if isinstance(content, str):
            body = content
        elif e.get("kind") == "plan":
            steps = "\n".join(f"  - {s}" for s in (content or {}).get("steps", []))
            body = f"summary: {(content or {}).get('summary', '')}\nsteps:\n{steps}"
        else:  # turn
            c = content or {}
            agreements = ", ".join(c.get("agreements", []))
            concerns = ", ".join(c.get("concerns", []))
            revised = "\n".join(f"  - {s}" for s in c.get("revised_steps", []))
            body = (
                f"response: {c.get('response', '')}\n"
                f"agreements: {agreements}\nconcerns: {concerns}\nrevised_steps:\n{revised}"
            )
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


def _planner_user(state: SharedState) -> str:
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        "目标代码仓库已在工作目录就绪(只读)。请【独立】基于该主题制定你的实现方案:"
        "summary / steps / tools_needed / risks。只出方案,不写代码,不要参考他人方案。"
    )


def _turn_user(state: SharedState) -> str:
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        f"目前为止的完整讨论记录(含对方方案、历轮发言、以及人的插话):\n"
        f"{render_transcript(state.discussion)}\n\n"
        "请基于以上给出你这一轮:response(论点/回应)、agreements(认同对方哪些点)、"
        "concerns(对对方方案的异议)、revised_steps(综合后你更新的计划步骤)。"
    )


def _consensus_user(state: SharedState) -> str:
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        f"完整讨论记录:\n{render_transcript(state.discussion)}\n\n"
        "请综合双方讨论(并尊重人的插话),产出共识实现方案:summary / steps / rationale / open_questions。"
    )


DISCUSS_PLANNER = RoleSpec(
    name="discuss_planner", agent_id="discuss_planner", tool_name="submit_plan",
    message_type=MessageType.PROPOSAL, content_model=PlannerOutput,
    system_prompt=(
        "你是 MACR 讨论中的规划者。独立地、只基于主题给出你自己的实现方案。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_planner_user,
)

DISCUSS_TURN = RoleSpec(
    name="discuss_turn", agent_id="discuss_turn", tool_name="submit_turn",
    message_type=MessageType.CRITIQUE, content_model=DiscussionTurn,
    system_prompt=(
        "你是 MACR 讨论中的一位参与者。基于完整讨论记录,真诚地与对方讨论:认同、质疑、补充、修订。"
        "目标是把方案谈得更好,而非迎合。输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_turn_user,
)

CONSENSUS = RoleSpec(
    name="consensus", agent_id="consensus", tool_name="submit_consensus",
    message_type=MessageType.DECISION, content_model=ConsensusPlan,
    system_prompt=(
        "你是 MACR 的共识汇总者(由 Claude 扮演)。综合整场讨论,产出一份双方认可、可执行的共识方案。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_consensus_user,
)
