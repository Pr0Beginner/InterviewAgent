from enum import StrEnum


class InterviewStatus(StrEnum):
    """投递记录支持的状态阶段。"""
    APPLIED = "已投递"
    RESUME_SCREENING = "简历筛选中"
    WRITTEN_TEST = "笔试中"
    PENDING_INTERVIEW = "待面试"
    FIRST_INTERVIEW = "一面"
    SECOND_INTERVIEW = "二面"
    THIRD_INTERVIEW = "三面"
    HR_INTERVIEW = "HR面"
    OFFER = "Offer"
    ENDED = "已结束"


INTERVIEW_STATUS_VALUES = tuple(status.value for status in InterviewStatus)
INTERVIEW_STATUS_CHECK_SQL = "current_status IN ({})".format(
    ", ".join(f"'{value}'" for value in INTERVIEW_STATUS_VALUES)
)
