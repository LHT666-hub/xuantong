from pydantic import BaseModel


class WorkflowResult(BaseModel):
    """工作流执行结果"""
    workflow_name: str
    status: str  # completed / failed / pending_human
    steps_completed: list[str] = []
    result_summary: str = ""
    data: dict = {}
