from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import requests


NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = "39858e638e45817d95d8c84eb197f8fc"
NOTION_VERSION = "2026-03-11"

BASE_URL = "https://api.notion.com/v1"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


TEST_ROW = {
    "Report": "Script test row",
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


def require_config() -> None:
    if not NOTION_TOKEN:
        raise RuntimeError("Set NOTION_TOKEN before running this script.")

    if not NOTION_DATABASE_ID:
        raise RuntimeError(
            "Set NOTION_DATABASE_ID before running this script."
        )


def notion_get(path: str) -> dict[str, Any]:
    response = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=30)

    if not response.ok:
        print("Notion API error:")
        print(response.status_code)
        print(response.text)

    response.raise_for_status()
    return response.json()


def notion_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload, timeout=30)

    if not response.ok:
        print("Notion API error:")
        print(response.status_code)
        print(response.text)

    response.raise_for_status()
    return response.json()


def get_first_data_source_id(database_id: str) -> str:
    database = notion_get(f"/databases/{database_id}")

    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise RuntimeError(
            "No data_sources found. Make sure you are using a database ID, "
            "not a page ID, and that the original database is shared with the integration."
        )

    print("Available data sources:")
    for source in data_sources:
        print(f"- {source.get('name', '<unnamed>')}: {source['id']}")

    return data_sources[0]["id"]


def resolve_data_source_id() -> str:

    return get_first_data_source_id(NOTION_DATABASE_ID)


def get_data_source_schema(data_source_id: str) -> dict[str, Any]:
    data_source = notion_get(f"/data_sources/{data_source_id}")
    return data_source["properties"]


def parse_number(raw_value: Any, property_schema: dict[str, Any]) -> float | int | None:
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


def parse_date(raw_value: Any) -> str | None:
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


def parse_checkbox(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value

    text = str(raw_value).strip().lower()
    return text in {"1", "true", "yes", "y", "ja", "x", "checked"}


def split_multi_select(raw_value: Any) -> list[dict[str, str]]:
    text = str(raw_value).strip()
    if not text:
        return []

    values = [value.strip() for value in text.split(",")]
    return [{"name": value} for value in values if value]


def build_page_property(
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
        number = parse_number(raw_value, property_schema)
        return {"number": number} if number is not None else None

    if property_type == "select":
        return {"select": {"name": text}}

    if property_type == "status":
        return {"status": {"name": text}}

    if property_type == "multi_select":
        options = split_multi_select(raw_value)
        return {"multi_select": options} if options else None

    if property_type == "date":
        date_value = parse_date(raw_value)
        return {"date": {"start": date_value}} if date_value else None

    if property_type == "checkbox":
        return {"checkbox": parse_checkbox(raw_value)}

    if property_type in {"url", "email", "phone_number"}:
        return {property_type: text}

    print(f"Skipping unsupported property type for {property_name!r}: {property_type}")
    return None


def build_page_properties(
    row: dict[str, Any],
    data_source_schema: dict[str, Any],
) -> dict[str, Any]:
    properties = {}

    for property_name, raw_value in row.items():
        property_schema = data_source_schema.get(property_name)
        if property_schema is None:
            print(f"Skipping unknown Notion property: {property_name!r}")
            continue

        property_value = build_page_property(property_name, raw_value, property_schema)
        if property_value is not None:
            properties[property_name] = property_value

    return properties


def add_row(
    row: dict[str, Any],
    data_source_id: str | None = None,
    data_source_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_source_id = data_source_id or resolve_data_source_id()
    data_source_schema = data_source_schema or get_data_source_schema(data_source_id)
    properties = build_page_properties(row, data_source_schema)

    if not properties:
        raise RuntimeError("No valid Notion properties were built from the row data.")

    payload = {
        "parent": {
            "data_source_id": data_source_id,
        },
        "properties": properties,
    }

    return notion_post("/pages", payload)


if __name__ == "__main__":
    require_config()

    data_source_id = resolve_data_source_id()
    data_source_schema = get_data_source_schema(data_source_id)

    print("========================")
    print("Connection established")
    print(f"Using data source: {data_source_id}")
    print("========================")

    created = add_row(TEST_ROW, data_source_id, data_source_schema)

    print("Created test row:")
    print(created["url"])
