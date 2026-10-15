"""One complete project projection shared by UI, Markdown and PDF workflows."""

from dataclasses import dataclass, fields
import sqlite3


@dataclass(frozen=True)
class ProjectData:
    project: sqlite3.Row
    urls: list[sqlite3.Row]
    notes: list[sqlite3.Row]
    checklist: list[sqlite3.Row]
    environment_variables: list[sqlite3.Row]
    access_accounts: list[dict[str, object]]

    def template_context(self) -> dict[str, object]:
        # asdict() would deepcopy sqlite3.Row; retain the exact immutable rows.
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def renderer_args(self) -> tuple:
        return (self.project, self.urls, self.notes, self.checklist,
                self.environment_variables, self.access_accounts)
