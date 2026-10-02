"""Shared request contract for the two recommendation backends."""

import json
import re


def parse_request(event):
    if not isinstance(event, dict):
        return None
    params = event.get("queryStringParameters")
    if not isinstance(params, dict):
        return None
    operation = params.get("type")
    lang = params.get("lang")
    if not isinstance(lang, str) or not lang.strip():
        return None
    if operation == "rec":
        identifier, pattern = params.get("userid"), r"[0-9]{1,7}"
    elif operation == "related":
        identifier, pattern = params.get("sku"), r"[0-9A-Z]{18}"
    else:
        return None
    if not isinstance(identifier, str) or re.fullmatch(pattern, identifier) is None:
        return None
    return operation, identifier, lang


def ml_response(code, body):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
