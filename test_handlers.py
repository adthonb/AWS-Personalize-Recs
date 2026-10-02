"""Offline contract checks; no AWS account or MySQL server is needed."""

import importlib
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError
import mysql.connector

personalize = importlib.import_module("lambda-api-personalize")
rds = importlib.import_module("lambda-api-rds")
SKU = "ABCDEFGHIJKLMNOPQR"


def event(operation="rec", **params):
    return {"queryStringParameters": {"type": operation, "lang": "en", **params}}


class HandlerTests(unittest.TestCase):
    def setUp(self):
        personalize.runtime_client.cache_clear()
        rds.cnx = None

    def assert_response(self, response, status, body):
        self.assertEqual(response["statusCode"], status)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(json.loads(response["body"]), body)

    def test_invalid_requests_do_not_touch_backends(self):
        invalid = [
            None, [], {}, {"queryStringParameters": None},
            {"queryStringParameters": []}, event(), event(userid=123),
            event(userid="123x"), event(userid="12345678"), event(userid="１２３"),
            event(userid="123\n"), event(userid=""), event(userid="123", lang=None),
            event(userid="123", lang=" "), event(userid="123", lang=[]),
            event(None, userid="123"), event("unknown", userid="123"),
            event("related", sku=SKU.lower()), event("related", sku=SKU + "X"),
            event("related", sku=SKU[:-1]), event("related", sku=None),
        ]
        with patch.object(personalize, "runtime_client") as sdk, patch.object(rds, "connection") as db:
            for module in (personalize, rds):
                for request in invalid:
                    with self.subTest(module=module.__name__, request=request):
                        self.assert_response(module.lambda_handler(request, None), 400,
                                             {"code": 400, "msg": "invalid request"})
            sdk.assert_not_called()
            db.assert_not_called()

    def test_personalize_exact_arguments_and_client_reuse(self):
        client = MagicMock()
        client.get_recommendations.return_value = {"itemList": [{"itemId": "A"}, {"itemId": "B"}]}
        with patch.dict(os.environ, {"REC_ARN": "rec-arn", "RELATED_ARN": "related-arn"}), \
                patch.object(personalize.boto3, "client", return_value=client) as factory:
            self.assert_response(personalize.lambda_handler(event(userid="123", sku=SKU), None),
                                 200, {"items": ["enA", "enB"]})
            client.get_recommendations.assert_called_with(campaignArn="rec-arn", userId="123")
            self.assert_response(personalize.lambda_handler(event("related", sku=SKU, userid="123"), None),
                                 200, {"items": ["enA", "enB"]})
            client.get_recommendations.assert_called_with(campaignArn="related-arn", itemId="th" + SKU)
            factory.assert_called_once_with("personalize-runtime")
            client.get_recommendations.return_value = {"itemList": []}
            self.assert_response(personalize.lambda_handler(event(userid="1"), None), 200, {"items": []})

    def test_personalize_errors(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(personalize, "runtime_client") as sdk:
            self.assertEqual(personalize.lambda_handler(event(userid="1"), None)["statusCode"], 500)
            sdk.assert_not_called()
        errors = [ClientError({"Error": {"Code": "AccessDeniedException", "Message": "private detail"}},
                              "GetRecommendations"), EndpointConnectionError(endpoint_url="https://example.invalid")]
        with patch.dict(os.environ, {"REC_ARN": "rec-arn"}), patch.object(personalize, "runtime_client") as sdk:
            for error in errors:
                sdk.return_value.get_recommendations.side_effect = error
                response = personalize.lambda_handler(event(userid="1"), None)
                self.assert_response(response, 502, {"code": 502, "msg": "recommendation service unavailable"})
            sdk.return_value.get_recommendations.side_effect = None
            sdk.return_value.get_recommendations.return_value = {}
            self.assertEqual(personalize.lambda_handler(event(userid="1"), None)["statusCode"], 500)

    def test_rds_queries_cursor_cleanup_and_empty_results(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.__iter__.return_value = iter([('["A", "B"]',), ('["C"]',)])
        with patch.object(rds, "connection", return_value=connection):
            self.assert_response(rds.lambda_handler(event(userid="123", sku=SKU), None),
                                 200, {"items": ["enA", "enB", "enC"]})
            cursor.execute.assert_called_with("SELECT items FROM userRecommend WHERE userId=%s", ("123",))
            cursor.__iter__.return_value = iter([])
            self.assert_response(rds.lambda_handler(event("related", sku=SKU, userid="123"), None),
                                 200, {"items": []})
            cursor.execute.assert_called_with("SELECT items FROM itemRelated WHERE itemId=%s", (SKU,))
            connection.cursor.assert_called_with(buffered=True)
            self.assertEqual(connection.cursor.return_value.__exit__.call_count, 2)

    def test_rds_connection_reuse_and_reconnect(self):
        config = {"RDS_USER": "test-user", "RDS_PASS": "test-only", "RDS_HOST": "db.invalid", "RDS_DB": "test-db"}
        with patch.dict(os.environ, config), patch.object(rds.mysql.connector, "connect") as connect:
            first = rds.connection()
            self.assertIs(first, rds.connection())
            connect.assert_called_once_with(user="test-user", password="test-only", host="db.invalid",
                                            database="test-db", connection_timeout=5, autocommit=True, use_pure=True)
            first.ping.assert_called_once_with(reconnect=True, attempts=1, delay=0)
            first.ping.side_effect = mysql.connector.InterfaceError("unreachable")
            self.assertEqual(rds.lambda_handler(event(userid="1"), None)["statusCode"], 502)

    def test_rds_bad_data_and_query_failure_close_cursor(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        with patch.object(rds, "connection", return_value=connection):
            for stored in ('invalid json', '{"A": 1}', '[1]', 'null'):
                with self.subTest(stored=stored):
                    cursor.__iter__.return_value = iter([(stored,)])
                    self.assertEqual(rds.lambda_handler(event(userid="1"), None)["statusCode"], 500)
            cursor.execute.side_effect = mysql.connector.Error("private database detail")
            self.assert_response(rds.lambda_handler(event(userid="1"), None), 502,
                                 {"code": 502, "msg": "recommendation service unavailable"})
            self.assertEqual(connection.cursor.return_value.__exit__.call_count, 5)
        with patch.dict(os.environ, {}, clear=True), patch.object(rds.mysql.connector, "connect") as connect:
            self.assertEqual(rds.lambda_handler(event(userid="1"), None)["statusCode"], 500)
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
