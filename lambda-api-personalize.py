"""API Gateway handler for campaign-based Amazon Personalize recommendations."""

import logging
import os
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from api_common import ml_response, parse_request

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def runtime_client():
    return boto3.client("personalize-runtime")


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
        logger.error("Missing campaign configuration or malformed Personalize response")
        return ml_response(500, {"code": 500, "msg": "internal server error"})
    except (BotoCoreError, ClientError) as exc:
        logger.error("Personalize request failed (%s)", type(exc).__name__)
        return ml_response(502, {"code": 502, "msg": "recommendation service unavailable"})


def ml_rec_api(userid, lang):
    campaign_arn = os.environ["REC_ARN"]
    result = runtime_client().get_recommendations(campaignArn=campaign_arn, userId=userid)
    return ml_response(200, {"items": [lang + item["itemId"] for item in result["itemList"]]})


def ml_related_api(sku, lang):
    campaign_arn = os.environ["RELATED_ARN"]
    result = runtime_client().get_recommendations(campaignArn=campaign_arn, itemId="th" + sku)
    return ml_response(200, {"items": [lang + item["itemId"] for item in result["itemList"]]})
