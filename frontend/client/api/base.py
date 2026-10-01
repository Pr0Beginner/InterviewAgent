from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ApiClient(ABC):
    """Mock 与 HTTP 客户端共用的前端接口定义。"""

    @abstractmethod
    def create_chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str = "interview-assistant",
        metadata: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """请求非流式的 OpenAI 兼容 Agent 响应。
        
        参数:
            messages: 按时间排序的完整对话，每条消息包含 role 和 content。
            model: Agent 对外模型别名，不是上游 DeepSeek 模型名。
            metadata: 字符串 Map，可包含 page_context 和 conversation_id。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            标准的 chat.completion 对象。
        """
        raise NotImplementedError

    @abstractmethod
    def stream_chat_completion(
        self, messages: list[dict[str, str]], model: str = "interview-assistant",
        metadata: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式接收标准响应块，不阻塞图形界面。
        
        参数:
            messages: 按时间排序的完整 role/content 对话历史。
            model: Agent 对外模型别名。
            metadata: 当前页面和可选的会话 ID。
            extensions: 可选的应用扩展 Map。
        
        返回值:
            chat.completion.chunk 对象的异步迭代器；请求失败时抛出异常。
        """
        raise NotImplementedError

    @abstractmethod
    def list_interviews(
        self,
        company_name: str | None = None,
        position_name: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """分页查询投递列表。
        
        参数:
            company_name: 可选的公司名称包含匹配条件。
            position_name: 可选的岗位名称包含匹配条件。
            status: 可选的精确状态条件；“全部”表示不按状态筛选。
            page: 页码，从 1 开始。
            page_size: 每页最多返回的记录数。
        
        返回值:
            当前页记录、分页信息和状态统计。
        """
        raise NotImplementedError

    @abstractmethod
    def update_interview_status(
        self,
        interview_id: int,
        target_status: str,
        interview_time: str | None = None,
        note: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """仅更新一条投递记录的状态。
        
        参数:
            interview_id: 投递记录 ID。
            target_status: 新的投递状态。
            interview_time: 新的面试时间；None 的清空或省略语义由具体实现决定。
            note: 可选的状态历史备注。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            更新后状态、原状态和同步信息。
        """
        raise NotImplementedError

    @abstractmethod
    def update_interview(
        self,
        interview_id: int,
        company_name: str,
        position_name: str,
        base_location: str,
        current_status: str,
        interview_time: str | None,
        interview_end_time: str | None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """保存投递表格中一行的所有可编辑字段。
        
        参数:
            interview_id: 投递记录 ID。
            company_name: 表格中显示的公司名称。
            position_name: 表格中显示的岗位名称。
            base_location: 表格中显示的工作地点。
            current_status: 选中的投递状态。
            interview_time: 选中的开始时间，无时间时为 None。
            interview_end_time: 选中的结束时间，无时间时为 None。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            已保存的投递记录。
        """
        raise NotImplementedError

    @abstractmethod
    def sync_email(
        self, limit: int = 50, scope: str = "unread",
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """开始扫描招聘邮件。
        
        参数:
            limit: 单个任务最多扫描的邮件数。
            scope: 扫描范围，支持 unread、read 和 all。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            已接收的邮件扫描任务信息。
        """
        raise NotImplementedError

    @abstractmethod
    def sync_feishu(
        self, extensions: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """将投递数据同步到飞书。
        
        参数:
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            同步结果的统计数量。
        """
        raise NotImplementedError

    @abstractmethod
    def recommend_jobs(
        self,
        cities: list[str],
        tech_stack: list[str],
        business_preferences: list[str] | None = None,
        keywords: list[str] | None = None,
        page: int = 1,
        page_size: int = 10,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """分页查询推荐岗位。
        
        参数:
            cities: 可接受的工作城市。
            tech_stack: 求职者的技术栈关键词。
            business_preferences: 可选的业务领域偏好。
            keywords: 可选的岗位搜索关键词。
            page: 页码，从 1 开始。
            page_size: 每页最多返回的岗位数。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            推荐岗位及分页信息。
        """
        raise NotImplementedError

    @abstractmethod
    def get_job_recommendation(self, recommendation_id: str) -> dict[str, Any]:
        """根据 ID 返回一条岗位推荐。
        
        参数:
            recommendation_id: 推荐记录 ID。
        
        返回值:
            完整的推荐信息，包含 JD 和来源链接。
        """
        raise NotImplementedError

    @abstractmethod
    def create_mock_interview(
        self,
        company_name: str | None,
        position_name: str,
        interview_round: str,
        interview_focus: list[str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建一场文本模拟面试。
        
        参数:
            company_name: 可选的目标公司。
            position_name: 目标岗位。
            interview_round: 目标面试轮次。
            interview_focus: 可选的重点考察方向。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            新建会话的信息及第一道题目。
        """
        raise NotImplementedError

    @abstractmethod
    def submit_mock_answer(
        self,
        session_id: str,
        question_id: str,
        answer: str,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """提交回答，获取评价及下一道题目。
        
        参数:
            session_id: 模拟面试会话 ID。
            question_id: 本次回答对应的题目 ID。
            answer: 用户的回答文本。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            评价、评分及可选的下一道题目。
        """
        raise NotImplementedError

    @abstractmethod
    def finish_mock_interview(
        self, session_id: str, extensions: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """结束模拟面试并生成总结。
        
        参数:
            session_id: 模拟面试会话 ID。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            总体评分、优点、不足及改进建议。
        """
        raise NotImplementedError
