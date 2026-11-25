ROUTER = {
    "type": "object",
    "properties": {"route": {"type": "string", "enum": ["medical", "direct"]}},
    "required": ["route"],
    "additionalProperties": False,
}

UNDERSTAND = {
    "type": "object",
    "properties": {
        "pubmed_query": {"type": "string"},
        "web_query": {"type": "string"},
    },
    "required": ["pubmed_query", "web_query"],
    "additionalProperties": False,
}

GRADE = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "relevance": {"type": "integer", "enum": [0, 1, 2]},
                },
                "required": ["id", "relevance"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["grades"],
    "additionalProperties": False,
}

VERIFY = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]},
                    "quote": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "verdict", "quote", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

CONFLICTS = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                },
                "required": ["ids", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conflicts"],
    "additionalProperties": False,
}