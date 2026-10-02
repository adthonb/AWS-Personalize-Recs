"""API Gateway handler for recommendations already stored in RDS MySQL."""

import json
import logging
import os

import mysql.connector

from api_common import ml_response, parse_request

logger = logging.getLogger(__name__)
cnx = None


def connection():
    global cnx
    if cnx is None:
        cnx = mysql.connector.connect(
            user=os.environ["RDS_USER"],
            password=os.environ["RDS_PASS"],
            host=os.environ["RDS_HOST"],
            database=os.environ["RDS_DB"],
            connection_timeout=5,
            autocommit=True,
            use_pure=True,
        )
    else:
        cnx.ping(reconnect=True, attempts=1, delay=0)
    return cnx


def lambda_handler(event, context):
    request = parse_request(event)
    if request is None:
        return ml_response(400, {"code": 400, "msg": "invalid request"})
    operation, identifier, lang = request
    try:
        if operation == "rec":
            return ml_rec_api(identifier, lang)
        return ml_related_api(identifier, lang)
    except (KeyError, ValueError, TypeError):
        logger.error("Missing database configuration or malformed stored recommendation data")
        return ml_response(500, {"code": 500, "msg": "internal server error"})
    except mysql.connector.Error as exc:
        logger.error("Database request failed (%s)", type(exc).__name__)
        return ml_response(502, {"code": 502, "msg": "recommendation service unavailable"})


def query_items(query, identifier, lang):
    items = []
    with connection().cursor(buffered=True) as cursor:
        cursor.execute(query, (identifier,))
        for (stored_items,) in cursor:
            row = json.loads(stored_items)
            if not isinstance(row, list) or not all(isinstance(item, str) for item in row):
                raise ValueError("Stored items must be a JSON array of strings")
            items.extend(lang + item for item in row)
    return ml_response(200, {"items": items})


def ml_rec_api(userid, lang):
    return query_items("SELECT items FROM userRecommend WHERE userId=%s", userid, lang)


def ml_related_api(sku, lang):
    return query_items("SELECT items FROM itemRelated WHERE itemId=%s", sku, lang)
