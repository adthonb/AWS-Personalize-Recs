import json
import mysql.connector
import os
import re

config = {
'user': os.environ['RDS_USER'],
'password': os.environ['RDS_PASS'],
'host': os.environ['RDS_HOST'],
'database': os.environ['RDS_DB'],
'raise_on_warnings': True
}
cnx = mysql.connector.connect(**config)
cursor = cnx.cursor()

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
    query = "SELECT items FROM userRecommend WHERE userId=%s"
    cursor.execute(query, (userid,))
    data = {"items": []}

    for (items,) in cursor:
        lang_items = [lang + s for s in json.loads(items)]
        data['items'].extend(lang_items)

    return ml_response(200, data)

def ml_related_api(sku, lang):
    query = "SELECT items FROM itemRelated WHERE itemId=%s"
    cursor.execute(query, (sku,))
    data = {"items": []}

    for (items,) in cursor:
        lang_items = [lang + s for s in json.loads(items)]
        data['items'].extend(lang_items)

    return ml_response(200, data)