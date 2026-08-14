"""面向用户的固定文案本地化。"""

# code、Tool 名、ID 和枚举值不在此翻译；这里只处理人类可读的固定提示。

from src.common.language import ResponseLanguage

_MESSAGES = {
    "zh-CN": {
        "unauthorized": "未授权访问",
        "conversation_not_found": "会话不存在",
        "agent_error": "Agent 执行失败",
        "request_resource_type": "我可以帮助你申请资源。请告诉我需要申请的资源类型。",
        "bucket_missing": "申请 bucket 还需要提供：{fields}。",
        "bucket_invalid": "参数还不完整，请补充缺失字段。",
        "ticket_created": "申请已创建，Ticket ID 为 {ticket_id}。",
    },
    "en": {
        "unauthorized": "Unauthorized",
        "conversation_not_found": "Conversation not found",
        "agent_error": "Agent execution failed",
        "request_resource_type": "I can help you request a resource. Please specify the resource type.",
        "bucket_missing": "The bucket request still needs: {fields}.",
        "bucket_invalid": "The parameters are incomplete. Please provide the missing fields.",
        "ticket_created": "Request created. Ticket ID: {ticket_id}.",
    },
}


def user_message(key: str, language: ResponseLanguage, **values: str) -> str:
    """返回指定语言的固定文案，并保留传入的特殊词原样。"""
    return _MESSAGES[language][key].format(**values)
