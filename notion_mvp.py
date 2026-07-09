from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import requests


NOTION_VERSION = "2026-03-11"
BASE_URL = "https://api.notion.com/v1"


TEST_ROW = {
    "Report": "New script!",
    "Model": "notion_mvp_test_model",
    "Fraction": "Dangerous Waste",
    "Machines": "smoldering-whale",
    "Evaluation of": "Capture",
    "Start": "2026-07-09",
    "End": "2026-07-20",
    "Classes": "background, hard_plastic, soft_plastic",
    "Accuracy": "91 %",
    "F1 Weighted": "90 %",
    "Macro Recall": "89 %",
    "F1 Macro": "88 %",
    "Test Size": 123,
}


DANISH_MONTHS = {
    "januar": 1,
    "februar": 2,
    "marts": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}


class NotionDatabase:
    """Small reusable client for adding rows to a Notion database/data source."""

    def __init__(
        self,
        *,
        token: str,
        database_id: str | None = None,
        data_source_id: str | None = None,
        notion_version: str = NOTION_VERSION,
        base_url: str = BASE_URL,
        timeout: int = 30,
        verbose: bool = True,
    ) -> None:
        if not token:
            raise RuntimeError("A Notion integration token is required.")

        if not database_id and not data_source_id:
            raise RuntimeError("Set either database_id or data_source_id.")

        self.token = token.strip()
        self.database_id = database_id.strip() if database_id else None
        self.data_source_id = data_source_id.strip() if data_source_id else None
        self.notion_version = notion_version
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        self.data_source_id = self.data_source_id or self._get_first_data_source_id()
        self.schema = self._get_data_source_schema()

        if self.verbose:
            print("========================")
            print("Connection established")
            print(f"Using data source: {self.data_source_id}")
            print("========================")

    @classmethod
    def from_env(cls, *, verbose: bool = True) -> NotionDatabase:
        """Create a client from NOTION_TOKEN plus NOTION_DATABASE_ID or NOTION_DATA_SOURCE_ID."""
        return cls(
            token=os.environ.get("NOTION_TOKEN", "").strip(),
            database_id=os.environ.get("NOTION_DATABASE_ID", "").strip() or None,
            data_source_id=os.environ.get("NOTION_DATA_SOURCE_ID", "").strip() or None,
            verbose=verbose,
        )

    def _get(self, path: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        return response.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}{path}",
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if not response.ok:
            print("Notion API error:")
            print(response.status_code)
            print(response.text)

        response.raise_for_status()

    def _get_first_data_source_id(self) -> str:
        if not self.database_id:
            raise RuntimeError("database_id is required when data_source_id is not set.")

        database = self._get(f"/databases/{self.database_id}")
        data_sources = database.get("data_sources", [])
        if not data_sources:
            raise RuntimeError(
                "No data_sources found. Make sure you are using a database ID, "
                "not a page ID, and that the original database is shared with the integration."
            )

        if self.verbose:
            print("Available data sources:")
            for source in data_sources:
                print(f"- {source.get('name', '<unnamed>')}: {source['id']}")

        return data_sources[0]["id"]

    def _get_data_source_schema(self) -> dict[str, Any]:
        data_source = self._get(f"/data_sources/{self.data_source_id}")
        return data_source["properties"]

    def add_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Add one Notion row/page. Dict keys must match Notion property names."""
        properties = self._build_page_properties(row)

        if not properties:
            raise RuntimeError("No valid Notion properties were built from the row data.")

        payload = {
            "parent": {
                "data_source_id": self.data_source_id,
            },
            "properties": properties,
        }

        return self._post("/pages", payload)

    def _build_page_properties(self, row: dict[str, Any]) -> dict[str, Any]:
        properties = {}

        for property_name, raw_value in row.items():
            property_schema = self.schema.get(property_name)
            if property_schema is None:
                if self.verbose:
                    print(f"Skipping unknown Notion property: {property_name!r}")
                continue

            property_value = self._build_page_property(property_name, raw_value, property_schema)
            if property_value is not None:
                properties[property_name] = property_value

        return properties

    def _build_page_property(
        self,
        property_name: str,
        raw_value: Any,
        property_schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        property_type = property_schema["type"]

        if raw_value is None or str(raw_value).strip() == "":
            return None

        text = str(raw_value).strip()

        if property_type == "title":
            return {"title": [{"text": {"content": text}}]}

        if property_type == "rich_text":
            return {"rich_text": [{"text": {"content": text}}]}

        if property_type == "number":
            number = self._parse_number(raw_value, property_schema)
            return {"number": number} if number is not None else None

        if property_type == "select":
            return {"select": {"name": text}}

        if property_type == "status":
            return {"status": {"name": text}}

        if property_type == "multi_select":
            options = self._split_multi_select(raw_value)
            return {"multi_select": options} if options else None

        if property_type == "date":
            date_value = self._parse_date(raw_value)
            return {"date": {"start": date_value}} if date_value else None

        if property_type == "checkbox":
            return {"checkbox": self._parse_checkbox(raw_value)}

        if property_type in {"url", "email", "phone_number"}:
            return {property_type: text}

        if self.verbose:
            print(f"Skipping unsupported property type for {property_name!r}: {property_type}")
        return None

    @staticmethod
    def _parse_number(raw_value: Any, property_schema: dict[str, Any]) -> float | int | None:
        if raw_value is None:
            return None

        if isinstance(raw_value, (int, float)):
            return raw_value

        text = str(raw_value).replace("\xa0", " ").strip()
        if not text:
            return None

        is_percent_text = "%" in text
        number_format = property_schema.get("number", {}).get("format")

        cleaned = text.replace("%", "").replace(" ", "").replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            print(f"Skipping number value that could not be parsed: {raw_value!r}")
            return None

        number = float(match.group(0))
        if number.is_integer():
            number = int(number)

        if number_format == "percent" and is_percent_text:
            return number / 100

        return number

    @staticmethod
    def _parse_date(raw_value: Any) -> str | None:
        if raw_value is None:
            return None

        text = str(raw_value).strip()
        if not text:
            return None

        try:
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            pass

        match = re.fullmatch(r"(\d{1,2})\.\s+([A-Za-zæøåÆØÅ]+)\s+(\d{4})", text)
        if match:
            day = int(match.group(1))
            month_name = match.group(2).lower()
            year = int(match.group(3))
            month = DANISH_MONTHS.get(month_name)
            if month:
                return datetime(year, month, day).date().isoformat()

        print(f"Skipping date value that could not be parsed: {raw_value!r}")
        return None

    @staticmethod
    def _parse_checkbox(raw_value: Any) -> bool:
        if isinstance(raw_value, bool):
            return raw_value

        text = str(raw_value).strip().lower()
        return text in {"1", "true", "yes", "y", "ja", "x", "checked"}

    @staticmethod
    def _split_multi_select(raw_value: Any) -> list[dict[str, str]]:
        text = str(raw_value).strip()
        if not text:
            return []

        values = [value.strip() for value in text.split(",")]
        return [{"name": value} for value in values if value]


if __name__ == "__main__":
    notion_db = NotionDatabase.from_env()
    created = notion_db.add_row(TEST_ROW)

    print("Created test row:")
    print(created["url"])
