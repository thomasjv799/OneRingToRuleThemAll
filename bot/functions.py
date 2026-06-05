"""LangGraph tools exposed to the LLM."""
import json
import db.client as db

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_vehicles",
            "description": "List all tracked vehicles with their document expiry dates.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_vehicle_expiry",
            "description": "Update a document expiry date for a vehicle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_id": {"type": "integer"},
                    "field": {
                        "type": "string",
                        "enum": [
                            "insurance_expiry", "pollution_expiry",
                            "fitness_expiry", "tax_expiry", "permit_expiry",
                        ],
                    },
                    "value": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                },
                "required": ["vehicle_id", "field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_games",
            "description": "List games the user is tracking for price drops.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watches",
            "description": "List watches the user is tracking for price drops.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def dispatch(name: str, args: dict, user_id: str) -> str:
    if name == "get_vehicles":
        return json.dumps(db.get_vehicles(), default=str)
    if name == "update_vehicle_expiry":
        ok = db.update_vehicle_expiry(args["vehicle_id"], args["field"], args["value"])
        return json.dumps({"updated": ok})
    if name == "get_games":
        return json.dumps(db.get_games(user_id), default=str)
    if name == "get_watches":
        return json.dumps(db.get_watches(user_id), default=str)
    return json.dumps({"error": f"Unknown tool: {name}"})
