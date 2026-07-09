import os
import requests


NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATA_SOURCE_ID"]

NOTION_VERSION = "2026-03-11"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"

response = requests.get(url, headers=HEADERS, timeout=30)





def notion_get(url: str) -> dict:
    response = requests.get(url, headers=HEADERS, timeout=30)

    if not response.ok:
        print("Notion API error:")
        print(response.status_code)
        print(response.text)

    response.raise_for_status()
    return response.json()


def notion_post(url: str, payload: dict) -> dict:
    response = requests.post(url, headers=HEADERS, json=payload, timeout=30)

    if not response.ok:
        print("Notion API error:")
        print(response.status_code)
        print(response.text)

    response.raise_for_status()
    return response.json()


def get_first_data_source_id(database_id: str) -> str:
    database = notion_get(f"https://api.notion.com/v1/databases/{database_id}")

    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise RuntimeError(
            "No data_sources found. Make sure you are using a database ID, "
            "not a page ID, and that the database is shared with the integration."
        )

    print("Available data sources:")
    for source in data_sources:
        print(f"- {source.get('name', '<unnamed>')}: {source['id']}")

    return data_sources[0]["id"]


def resolve_data_source_id() -> str:

    if NOTION_DATABASE_ID:
        return get_first_data_source_id(NOTION_DATABASE_ID)

    raise RuntimeError(
        "Set either NOTION_DATABASE_ID or NOTION_DATA_SOURCE_ID."
    )


def add_row(navnet: str, nummeret: float, valget: str) -> dict:
    data_source_id = resolve_data_source_id()

    payload = {
        "parent": {
            "data_source_id": data_source_id,
        },
        "properties": {
            "Navnet": {
                "title": [
                    {
                        "text": {
                            "content": navnet,
                        }
                    }
                ]
            },
            "Nummeret": {
                "number": nummeret,
            },
            "Valget": {
                "select": {
                    "name": valget,
                }
            },
        },
    }

    return notion_post("https://api.notion.com/v1/pages", payload)


if __name__ == "__main__":
    try:
        notion_get(f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}")
        print("========================")
        print("Connection established")
        print("========================")
    except: 
        raise ValueError("Connection could not be established. Check api key or database ID.")

    created = add_row(
        navnet="Ny række fra Python",
        nummeret=10,
        valget="to",
    )
    add_row(navnet="Ny række fra Python", nummeret=3, valget="fem")

    print("Created row:")
    print(created["url"])