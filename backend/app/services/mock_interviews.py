"""由 Skill 驱动的模拟面试，使用本地 JSON 持久化并控制并发。"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.app.agent.provider import DeepSeekProvider
from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError
from backend.app.schemas.business import InterviewQuestion, AnswerEvaluation, InterviewReport
from backend.app.storage.local import LocalStateStore

SKILL = (Path(__file__).resolve().parents[1] / "agent/skills/mock_interview.md").read_text(encoding="utf-8")


class MockInterviewService:
    """生成题目、评价回答，并恢复已持久化的面试会话。"""

    def __init__(self, state_store=None, provider=None, max_questions=None):
        """注入本地状态文件、模型和题目数量上限，便于测试。"""
        self.state_store = state_store or LocalStateStore()
        self.provider = provider or DeepSeekProvider(get_settings())
        self.max_questions = max_questions or get_settings().mock_interview_max_questions

    async def create(self, request) -> dict:
        """生成第一道题，仅在成功后保存面试会话。"""
        context = request.model_dump(exclude={"extensions"})
        question = await self.provider.structured(SKILL, {"task": "提出第一个问题", "context": context}, InterviewQuestion)
        session_id, question_id = "mock-" + uuid4().hex, "q-" + uuid4().hex
        created_at = datetime.now().isoformat()
        self.state_store.put("mock_sessions", session_id, {
            "id": session_id,
            "status": "in_progress",
            "version": 1,
            "context": context,
            "turns": [{"question_id": question_id, "question": question.question}],
            "report": None,
            "created_at": created_at,
        })
        return {"session_id": session_id, "question_id": question_id, "question": question.question, "status": "in_progress", "created_at": created_at}

    def get(self, session_id: str) -> dict:
        """恢复一场已保存的面试，包括待回答题目和总结。"""
        row = self.state_store.get("mock_sessions", session_id)
        if row is None:
            raise ApplicationError("SESSION_NOT_FOUND", "模拟面试不存在。", status_code=404)
        return {"session_id": row["id"], "status": row["status"], "version": row["version"],
                "context": row["context"], "turns": row["turns"], "report": row["report"]}

    async def answer(self, session_id: str, request) -> dict:
        """仅评价当前待回答的题目，会话版本未变化时才提交结果。"""
        state = self.get(session_id)
        for turn in state["turns"]:
            if turn["question_id"] == request.question_id and "result" in turn:
                if turn["answer"] == request.answer:
                    return turn["result"]
                raise ApplicationError("ANSWER_ALREADY_SAVED", "这道题已提交回答，不能覆盖。", status_code=409)
        if state["status"] != "in_progress" or state["turns"][-1]["question_id"] != request.question_id:
            raise ApplicationError("QUESTION_CONFLICT", "题目已变化或面试已结束，请刷新。", status_code=409)
        evaluation = await self.provider.structured(SKILL, {
            "task": "评价当前回答并决定追问或下一题", "context": state["context"],
            "history": state["turns"], "answer": request.answer,
        }, AnswerEvaluation)
        completed = len(state["turns"]) >= self.max_questions
        next_id = None if completed else "q-" + uuid4().hex
        result = evaluation.model_dump()
        result.update(question_id=next_id, question=None if completed else evaluation.question,
                      status="completed" if completed else "in_progress")
        turns = [dict(turn) for turn in state["turns"]]
        turns[-1].update(answer=request.answer, result=result)
        if not completed:
            turns.append({"question_id": next_id, "question": evaluation.question})
        self._save(session_id, state["version"], turns=turns, status="awaiting_summary" if completed else "in_progress")
        return result

    async def finish(self, session_id: str) -> dict:
        """根据实际回答生成并保存总结；重复结束操作保持幂等。"""
        state = self.get(session_id)
        if state["report"] is not None:
            return state["report"]
        answered = [turn for turn in state["turns"] if "answer" in turn]
        if answered:
            report = await self.provider.structured(SKILL, {"task": "结束面试并总结", "context": state["context"], "answers": answered}, InterviewReport)
            result = report.model_dump()
        else:
            result = {"overall_score": 0, "summary": "尚未提交回答，无法评价。", "strengths": [], "weaknesses": [], "suggestions": ["完成至少一道题后再生成评价。"]}
        result.update(session_id=session_id, finished_at=datetime.now().isoformat())
        self._save(session_id, state["version"], report=result, status="completed")
        return result

    def _save(self, session_id: str, expected_version: int, **values) -> None:
        """仅在没有其他回答或结束请求更新会话时提交生成结果。"""
        self.state_store.update_if_version("mock_sessions", session_id, expected_version, values)
