"""Shared option values and original export labels; UI translations are request scoped."""


STATUS_OPTIONS = [
    ("maintenance", "維護中"),
    ("completed", "已結案"),
    ("handover", "移交中"),
]
URL_TYPES = [
    ("production", "正式環境"),
    ("staging", "測試環境"),
    ("git", "Git Repository"),
    ("figma", "Figma"),
    ("api_docs", "API 文件"),
    ("other", "其他"),
]
NOTE_CATEGORIES = [
    ("note", "一般備註"),
    ("caution", "注意事項"),
    ("known_issue", "Known Issue"),
    ("workaround", "Workaround"),
]
PRIORITIES = [("normal", "一般"), ("high", "重要"), ("critical", "關鍵")]
CHECKLIST_CATEGORIES = [
    ("account", "帳號與權限"),
    ("deployment", "部署"),
    ("environment", "環境"),
    ("service", "第三方服務"),
    ("other", "其他"),
]
ENVIRONMENTS = [
    ("local", "Local"),
    ("staging", "Staging"),
    ("production", "Production"),
]
ACCESS_ACCOUNT_CATEGORIES = [
    ("database", "資料庫帳號"),
    ("website", "網站／測試帳號"),
    ("server", "主機／SSH"),
    ("cloud", "雲端／IAM"),
    ("service", "第三方服務"),
    ("other", "其他"),
]
ACCESS_ENVIRONMENTS = [
    ("local", "Local"),
    ("development", "開發"),
    ("test", "測試"),
    ("staging", "Staging"),
    ("production", "Production"),
    ("other", "其他"),
]


def status_label(status: str) -> str:
    return dict(STATUS_OPTIONS).get(status, status)


def url_type_label(url_type: str) -> str:
    return dict(URL_TYPES).get(url_type, url_type)


def note_category_label(category: str) -> str:
    return dict(NOTE_CATEGORIES).get(category, category)


def checklist_category_label(category: str) -> str:
    return dict(CHECKLIST_CATEGORIES).get(category, category)


def priority_label(priority: str) -> str:
    return dict(PRIORITIES).get(priority, priority)


def environment_label(environment: str) -> str:
    return dict(ENVIRONMENTS).get(environment, environment)


def access_environment_label(environment: str) -> str:
    return dict(ACCESS_ENVIRONMENTS).get(environment, environment)


def access_account_category_label(category: str) -> str:
    return dict(ACCESS_ACCOUNT_CATEGORIES).get(category, category)
