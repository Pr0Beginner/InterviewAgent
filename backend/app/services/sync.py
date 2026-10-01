"""持久化飞书同步记录，并按版本确认待同步项是否完成。"""

from datetime import datetime
from hashlib import sha256

from sqlalchemy import select, update

from backend.app.core.exceptions import ApplicationError
from backend.app.db.mysql import get_session_factory
from backend.app.integrations.feishu import FeishuClient, SYNC_LOCK, FIELDS
from backend.app.models import AgentOperation, FeishuSyncItem, JobApplication, ApplicationStatusHistory
from backend.app.schemas.interviews import InterviewRecord


def queue_sync(session, application_id: int) -> None:
    """在投递变更的同一事务中暂存待同步记录。"""
    item = session.get(FeishuSyncItem, application_id)
    if item is None:
        session.add(FeishuSyncItem(application_id=application_id, status="pending", version=1, attempts=0))
    else:
        item.version += 1
        item.status = "pending"


def sync_feishu(session_factory=None, client=None, direction: str = "both") -> dict:
    """导出一致的数据快照，保留同步失败记录并检测远端人工修改。"""
    if not isinstance(direction, str) or direction not in {"both", "pull", "push"}:
        raise ApplicationError("FEISHU_DIRECTION_INVALID", "direction 只能是 both、pull 或 push。", status_code=422)
    factory = session_factory or get_session_factory()
    client = client or FeishuClient()
    settings = getattr(client, "settings", None)
    document = getattr(settings, "feishu_progress_token", None) or getattr(settings, "feishu_document_token", "test") or "unset"
    export_id = "feishu-" + sha256(document.encode()).hexdigest()[:50]
    with SYNC_LOCK:
        current = client.read()
        if current.get("source_type") == "progress_sheet":
            return _sync_native(factory, client, current, export_id, direction)
        if current["status"] != "success":
            raise ApplicationError("FEISHU_NOT_CONFIGURED", "请配置 FEISHU_Progress_TOKEN；程序复用本机飞书 CLI 登录态。", status_code=503)
        with factory() as session:
            rows = list(session.scalars(select(JobApplication).order_by(JobApplication.id)))
            records = [InterviewRecord.model_validate(row).model_dump(mode="json") for row in rows]
            versions = {item.application_id: item.version for item in session.scalars(select(FeishuSyncItem))}
            previous = session.get(AgentOperation, export_id)
            normalize = lambda rows: [{key: str(row.get(key) or "") for key in FIELDS} for row in rows]
            if previous and normalize(current["records"]) != normalize(previous.result["records"]):
                if normalize(current["records"]) != normalize(records):
                    raise ApplicationError("FEISHU_CONFLICT", "飞书汇总被手动修改，请先核对冲突后再同步。", status_code=409)
            if not previous and current["records"] and normalize(current["records"]) != normalize(records):
                raise ApplicationError("FEISHU_CONFLICT", "飞书已有不同的 IA 汇总数据，请先核对，未覆盖。", status_code=409)
        try:
            client.write(records, current)
        except ApplicationError as exc:
            with factory() as session:
                for app_id in versions:
                    session.execute(update(FeishuSyncItem).where(FeishuSyncItem.application_id == app_id).values(status="pending", last_error=exc.message, attempts=FeishuSyncItem.attempts + 1))
                session.commit()
            raise
        with factory() as session:
            for app_id, version in versions.items():
                session.execute(update(FeishuSyncItem).where(FeishuSyncItem.application_id == app_id, FeishuSyncItem.version == version).values(status="success", last_error=None))
            receipt = session.get(AgentOperation, export_id)
            if receipt:
                receipt.result = {"records": records}
            else:
                session.add(AgentOperation(id=export_id, result={"records": records}))
            session.commit()
        return {"status": "success", "success_count": len(records), "failed_count": 0, "synced_at": datetime.now().isoformat()}


def _sync_native(factory, client, current: dict, export_id: str, direction: str) -> dict:
    """导入明确的远端记录，只推送本地待同步项；含糊状态与人工冲突不覆盖。

    参数:
        direction: both 双向合并、pull 仅导入、push 仅推送。
        current: 已完整读取且带真实行坐标的飞书快照。
    """
    from backend.app.integrations.feishu_sources import business_key, local_time
    if direction not in {"both", "pull", "push"}:
        raise ApplicationError("FEISHU_DIRECTION_INVALID", "direction 只能是 both、pull 或 push。", status_code=422)
    if current["schedule"]["status"] == "failed":
        raise ApplicationError("FEISHU_DATE_UNAVAILABLE", current["schedule"]["error"], status_code=503)
    imported = 0
    needs_review = list(current.get("needs_review", []))
    with factory() as session:
        local_rows = list(session.scalars(select(JobApplication).with_for_update()))
        pending = {item.application_id: item.version for item in session.scalars(select(FeishuSyncItem).where(FeishuSyncItem.status == "pending").with_for_update())}
        receipt = session.get(AgentOperation, export_id)
        baseline = receipt.result.get("remote_records", []) if receipt else []
        snapshots = []
        versions = {}
        for row in local_rows:
            if direction == "pull" or row.id not in pending:
                continue
            desired = InterviewRecord.model_validate(row).model_dump(mode="json")
            other = [record for record in current["records"] if business_key(record) == business_key(desired)]
            old = [record for record in baseline if business_key(record) == business_key(desired)]
            if len(other) != 1:
                raise ApplicationError("FEISHU_RECORD_AMBIGUOUS", "待同步记录没有唯一对应的飞书进度行，未执行写入。", status_code=409)
            # 只检查本次会推送的记录，其他人的编辑或不相关行不会引发整表覆盖。
            for field in ("current_status", "interview_time"):
                remote_value = other[0].get(field)
                local_value = desired.get(field)
                if field == "interview_time":
                    remote_value, local_value = local_time(remote_value), local_time(local_value)
                if remote_value != local_value and (not old or remote_value != old[0].get(field)):
                    raise ApplicationError("FEISHU_CONFLICT", "飞书记录被手动修改或尚无同步基线，请核对后再操作。", status_code=409)
            snapshots.append(desired)
            versions[row.id] = pending[row.id]
        if direction != "push":
            for remote in current["records"]:
                if not remote["current_status"]:
                    continue
                matches = [row for row in local_rows if business_key(InterviewRecord.model_validate(row).model_dump()) == business_key(remote)]
                if len(matches) > 1:
                    needs_review.append({"source_id": remote["id"], "company_name": remote["company_name"], "reason": "数据库存在同公司、岗位和地点的多条记录"})
                    continue
                row = matches[0] if matches else None
                if row is not None and row.id in pending:
                    continue
                if row is None:
                    row = JobApplication(company_name=remote["company_name"], position_name=remote["position_name"], base_location=remote["base_location"], current_status=remote["current_status"])
                    session.add(row)
                    session.flush()
                    local_rows.append(row)
                    previous_status = None
                else:
                    previous_status = row.current_status
                time = datetime.fromisoformat(remote["interview_time"]) if remote.get("interview_time") else None
                changed = previous_status != remote["current_status"] or row.interview_time != time
                row.current_status, row.interview_time = remote["current_status"], time
                if previous_status != row.current_status:
                    session.add(ApplicationStatusHistory(application_id=row.id, previous_status=previous_status, current_status=row.current_status,
                                                         change_source="feishu", note="从原进度表导入；未注明的岗位和地点留空"))
                if changed:
                    row.updated_at = datetime.now()
                    imported += 1
        session.commit()
    try:
        if snapshots:
            client.write(snapshots, current)
    except ApplicationError as exc:
        with factory() as session:
            for app_id in versions:
                session.execute(update(FeishuSyncItem).where(FeishuSyncItem.application_id == app_id).values(status="pending", last_error=exc.message, attempts=FeishuSyncItem.attempts + 1))
            session.commit()
        raise
    observed = client.read() if snapshots else current
    with factory() as session:
        for app_id, version in versions.items():
            session.execute(update(FeishuSyncItem).where(FeishuSyncItem.application_id == app_id, FeishuSyncItem.version == version).values(status="success", last_error=None))
        receipt = session.get(AgentOperation, export_id)
        remote_records = [dict(row) for row in observed["records"]]
        if direction == "pull" and pending:
            # 只读导入不能把本地脏行的远端冲突偷偷认作已确认的同步基线。
            with_pending = {business_key(InterviewRecord.model_validate(row).model_dump()) for row in local_rows if row.id in pending}
            remote_records = [row for row in remote_records if business_key(row) not in with_pending]
            remote_records += [row for row in baseline if business_key(row) in with_pending]
        result = {"remote_records": remote_records}
        if receipt:
            receipt.result = result
        else:
            session.add(AgentOperation(id=export_id, result=result))
        session.commit()
    return {"status": "success", "success_count": imported + len(snapshots), "imported_count": imported, "exported_count": len(snapshots),
            "failed_count": 0, "needs_review": needs_review, "synced_at": datetime.now().isoformat()}
