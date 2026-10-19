"""Validated, immutable document choices; independent of HTTP and database state."""

from dataclasses import dataclass
import json
from pathlib import Path

from .errors import ApplicationError


SECTION_LABELS = (
    ("description", "專案描述"), ("urls", "重要 URL"), ("notes", "備註與注意事項"),
    ("environment", "環境變數說明"), ("accounts", "帳號與存取資料"), ("checklist", "交接清單"),
)
SECTION_IDS = tuple(key for key, _ in SECTION_LABELS)
DOCUMENT_EN = json.loads((Path(__file__).parent / "locales/export-en.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ExportOptions:
    language: str
    sections: tuple[str, ...]

    def __post_init__(self):
        if self.language not in {"zh-Hant", "en"} or not self.sections or any(
            section not in SECTION_IDS for section in self.sections
        ) or len(set(self.sections)) != len(self.sections):
            raise ApplicationError(400, "請選擇有效的文件語言及至少一個匯出章節。")

    def label(self, value: str) -> str:
        if self.language == "en":
            return DOCUMENT_EN.get(value, value)
        return {"Notes & Cautions": "備註與注意事項", "Handover Checklist": "交接清單",
                "Project overview and handover reference": "專案概覽與交接參考",
                "Project handover notes": "專案交接備註", "Git Repository": "程式碼庫",
                "Known Issue": "已知問題", "Workaround": "替代方案", "Local": "本機",
                "Staging": "測試環境", "Production": "正式環境"}.get(value, value)
