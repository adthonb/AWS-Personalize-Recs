import json
import boto3
import os
import re

def lambda_handler(event, context):
    if 'sku' in event['queryStringParameters']:
        sku = event['queryStringParameters']['sku']
        userid = ''
    if 'userid' in event['queryStringParameters']:
        userid = event['queryStringParameters']['userid']
        sku = ''

    apitype = event['queryStringParameters']['type']
    lang = event['queryStringParameters']['lang']

    user_reg = re.compile(r"[0-9]{1,7}")
    sku_reg = re.compile(r"[0-9A-Z]{18}")

    if user_reg.match(userid) or apitype == 'rec':
        return ml_rec_api(userid, lang)
    elif sku_reg.match(sku) or apitype == 'related':
        return ml_related_api(sku, lang)
    else:
        return ml_response(400 , {'code': 400, 'msg': 'invalid request'})

def ml_response(code, body):
    return {
        'statusCode': code,
        'body': json.dumps(body)
    }

def ml_rec_api(userid, lang):
    personalizeRt = boto3.client('personalize-runtime')
    data = {"items": []}
    response = personalizeRt.get_recommendations(
    campaignArn = os.environ['REC_ARN'],
    userId = userid)

    for item in response['itemList']:
        data['items'].append(lang + item['itemId'])

    return ml_response(200, data)

def ml_related_api(sku, lang):
    personalizeRt = boto3.client('personalize-runtime')
    data = {"items": []}
    response = personalizeRt.get_recommendations(
    campaignArn = os.environ['RELATED_ARN'],
    itemId = 'th'+sku)

    for item in response['itemList']:
        data['items'].append(lang + item['itemId'])

    return ml_response(200, data)