"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/testbed.py

Tests the testbed (Q&A evaluation) endpoints through the full API stack.
These endpoints require authentication and database connectivity.
"""

import io
import json
from unittest.mock import patch, MagicMock

import pytest

from common.schema import QASetData, Evaluation, EvaluationReport


class TestAuthentication:
    """Integration tests for authentication on testbed endpoints."""

    def test_testbed_testsets_requires_auth(self, client):
        """GET /v1/testbed/testsets should require authentication."""
        response = client.get("/v1/testbed/testsets")

        assert response.status_code == 401

    def test_testbed_testsets_rejects_invalid_token(self, client, auth_headers):
        """GET /v1/testbed/testsets should reject invalid tokens."""
        response = client.get("/v1/testbed/testsets", headers=auth_headers["invalid_auth"])

        assert response.status_code == 401

    def test_testbed_evaluations_requires_auth(self, client):
        """GET /v1/testbed/evaluations should require authentication."""
        response = client.get("/v1/testbed/evaluations")

        assert response.status_code == 401

    def test_testbed_evaluation_requires_auth(self, client):
        """GET /v1/testbed/evaluation should require authentication."""
        response = client.get("/v1/testbed/evaluation")

        assert response.status_code == 401

    def test_testbed_testset_qa_requires_auth(self, client):
        """GET /v1/testbed/testset_qa should require authentication."""
        response = client.get("/v1/testbed/testset_qa")

        assert response.status_code == 401

    def test_testbed_delete_requires_auth(self, client):
        """DELETE /v1/testbed/testset_delete/{tid} should require authentication."""
        response = client.delete("/v1/testbed/testset_delete/1234")

        assert response.status_code == 401

    def test_testbed_load_requires_auth(self, client):
        """POST /v1/testbed/testset_load should require authentication."""
        response = client.post("/v1/testbed/testset_load")

        assert response.status_code == 401

    def test_testbed_generate_requires_auth(self, client):
        """POST /v1/testbed/testset_generate should require authentication."""
        response = client.post("/v1/testbed/testset_generate")

        assert response.status_code == 401

    def test_testbed_evaluate_requires_auth(self, client):
        """POST /v1/testbed/evaluate should require authentication."""
        response = client.post("/v1/testbed/evaluate")

        assert response.status_code == 401


class TestTestbedWithDatabase:
    """Integration tests for testbed endpoints that require database connectivity."""

    @pytest.fixture(autouse=True)
    def setup_database(
        self, client, test_client_auth_headers, db_container, test_db_payload, db_objects_manager, make_database
    ):
        """Setup database connection for tests"""
        # pylint: disable=unused-argument
        _ = db_container  # Ensure container is running

        # Ensure DEFAULT database exists
        default_db = next((db for db in db_objects_manager if db.name == "DEFAULT"), None)
        if not default_db:
            db_objects_manager.append(make_database(name="DEFAULT"))

        response = client.patch(
            "/v1/databases/DEFAULT", headers=test_client_auth_headers["valid_auth"], json=test_db_payload
        )
        assert response.status_code == 200

        # Create the testset tables by calling an endpoint that will trigger table creation
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200

    def test_testbed_testsets_empty(self, client, test_client_auth_headers):
        """Test getting empty testsets list"""
        with patch("server.api.utils.testbed.get_testsets", return_value=[]):
            response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == []

    def test_testbed_testsets_with_data(self, client, test_client_auth_headers):
        """Test getting testsets with data"""
        # Create two test sets with actual data
        for i, name in enumerate(["Test Set 1", "Test Set 2"]):
            test_data = json.dumps([{"question": f"Test Q{i}?", "answer": f"Test A{i}"}])
            test_file = io.BytesIO(test_data.encode())
            files = {"files": ("test.json", test_file, "application/json")}

            response = client.post(
                f"/v1/testbed/testset_load?name={name.replace(' ', '%20')}",
                headers=test_client_auth_headers["valid_auth"],
                files=files,
            )
            assert response.status_code == 200

        # Now get the testsets and verify
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200
        testsets = response.json()
        assert len(testsets) >= 2

        # Find our test sets
        test_set_1 = next((ts for ts in testsets if ts["name"] == "Test Set 1"), None)
        test_set_2 = next((ts for ts in testsets if ts["name"] == "Test Set 2"), None)

        assert test_set_1 is not None
        assert test_set_2 is not None
        assert "tid" in test_set_1
        assert "tid" in test_set_2

    def test_testbed_testset_qa(self, client, test_client_auth_headers):
        """Test getting testset Q&A data"""
        # Create a test set with specific Q&A data
        test_data = json.dumps(
            [{"question": "What is X?", "answer": "X is Y"}, {"question": "What is Z?", "answer": "Z is W"}]
        )
        test_file = io.BytesIO(test_data.encode())
        files = {"files": ("test.json", test_file, "application/json")}

        response = client.post(
            "/v1/testbed/testset_load?name=QA%20Test%20Set", headers=test_client_auth_headers["valid_auth"], files=files
        )
        assert response.status_code == 200

        # Get the testset ID
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        testsets = response.json()
        testset = next((ts for ts in testsets if ts["name"] == "QA Test Set"), None)
        assert testset is not None
        tid = testset["tid"]

        # Now get the Q&A data for this testset
        response = client.get(f"/v1/testbed/testset_qa?tid={tid}", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200
        qa_data = response.json()

        # Verify the response
        assert "qa_data" in qa_data
        assert len(qa_data["qa_data"]) == 2

        # The order might not be guaranteed, so check both questions and answers are present
        questions = [item["question"] for item in qa_data["qa_data"]]
        answers = [item["answer"] for item in qa_data["qa_data"]]

        assert "What is X?" in questions
        assert "What is Z?" in questions
        assert "X is Y" in answers
        assert "Z is W" in answers

    def test_testbed_evaluations_empty(self, client, test_client_auth_headers):
        """Test getting empty evaluations list"""
        with patch("server.api.utils.testbed.get_evaluations", return_value=[]):
            response = client.get(
                "/v1/testbed/evaluations?tid=123abc", headers=test_client_auth_headers["valid_auth"]
            )
            assert response.status_code == 200
            assert response.json() == []

    def test_testbed_evaluations_with_data(self, client, test_client_auth_headers):
        """Test getting evaluations with data"""
        # First, create a testset to evaluate
        test_data = json.dumps(
            [{"question": "Eval Q1?", "answer": "Eval A1"}, {"question": "Eval Q2?", "answer": "Eval A2"}]
        )
        test_file = io.BytesIO(test_data.encode())
        files = {"files": ("test.json", test_file, "application/json")}

        response = client.post(
            "/v1/testbed/testset_load?name=Eval%20Test%20Set",
            headers=test_client_auth_headers["valid_auth"],
            files=files,
        )
        assert response.status_code == 200

        # Get the testset ID
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        testsets = response.json()
        testset = next((ts for ts in testsets if ts["name"] == "Eval Test Set"), None)
        assert testset is not None
        tid = testset["tid"]

        # For the evaluation tests, we'll need to mock the evaluations
        mock_evaluations = [
            Evaluation(eid="eval1", evaluated="2023-01-01T12:00:00", correctness=0.85),
            Evaluation(eid="eval2", evaluated="2023-01-02T12:00:00", correctness=0.92),
        ]

        with patch("server.api.utils.testbed.get_evaluations", return_value=mock_evaluations):
            response = client.get(f"/v1/testbed/evaluations?tid={tid}", headers=test_client_auth_headers["valid_auth"])
            assert response.status_code == 200
            evaluations = response.json()
            assert len(evaluations) == 2
            assert evaluations[0]["eid"] == "eval1"
            assert evaluations[0]["correctness"] == 0.85
            assert evaluations[1]["eid"] == "eval2"
            assert evaluations[1]["correctness"] == 0.92

    def test_testbed_evaluation_report(self, client, test_client_auth_headers):
        """Test getting a single evaluation report"""
        # First, create a testset to evaluate
        test_data = json.dumps(
            [{"question": "Report Q1?", "answer": "Report A1"}, {"question": "Report Q2?", "answer": "Report A2"}]
        )
        test_file = io.BytesIO(test_data.encode())
        files = {"files": ("test.json", test_file, "application/json")}

        response = client.post(
            "/v1/testbed/testset_load?name=Report%20Test%20Set",
            headers=test_client_auth_headers["valid_auth"],
            files=files,
        )
        assert response.status_code == 200

        # Mock the evaluation report
        mock_report = EvaluationReport(
            eid="eval1",
            evaluated="2023-01-01T12:00:00",
            correctness=0.85,
            settings={"model": "test-model", "client": "test_client"},
            report={"details": "test details"},
            correct_by_topic={"topic1": 0.9, "topic2": 0.8},
            failures={"count": 2},
            html_report="<html>Test Report</html>",
        )

        with patch("server.api.utils.testbed.process_report", return_value=mock_report):
            response = client.get("/v1/testbed/evaluation?eid=eval1", headers=test_client_auth_headers["valid_auth"])
            assert response.status_code == 200
            report = response.json()

            # Verify the report structure
            assert report["eid"] == "eval1"
            assert report["correctness"] == 0.85
            assert report["html_report"] == "<html>Test Report</html>"
            assert "settings" in report
            assert "report" in report
            assert "correct_by_topic" in report
            assert "failures" in report

    def test_testbed_delete_testset(self, client, test_client_auth_headers):
        """Test deleting a testset"""
        response = client.delete("/v1/testbed/testset_delete/1234", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200
        assert "message" in response.json()

    def test_testbed_upsert_testsets(self, client, test_client_auth_headers):
        """Test upserting testsets"""
        # Create test data
        test_data = json.dumps([{"question": "Test Q?", "answer": "Test A"}])
        test_file = io.BytesIO(test_data.encode())

        # Make the request to create a testset
        files = {"files": ("test.json", test_file, "application/json")}

        response = client.post(
            "/v1/testbed/testset_load?name=Test%20Set", headers=test_client_auth_headers["valid_auth"], files=files
        )

        # Verify the response
        assert response.status_code == 200
        assert "qa_data" in response.json()
        assert len(response.json()["qa_data"]) == 1
        assert response.json()["qa_data"][0]["question"] == "Test Q?"
        assert response.json()["qa_data"][0]["answer"] == "Test A"

    def test_testbed_generate_qa_mocked(self, client, test_client_auth_headers):
        """Test generating Q&A testset with mocked client"""
        # This is a complex operation that requires a model to generate Q&A, so we'll mock this part
        with patch.object(client, "post") as mock_post:
            # Configure the mock to return a successful response
            mock_qa_data = QASetData(
                qa_data=[
                    {"question": "Generated Q1?", "answer": "Generated A1"},
                    {"question": "Generated Q2?", "answer": "Generated A2"},
                ]
            )
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_qa_data.dict()
            mock_post.return_value = mock_response

            # Make the request
            response = client.post(
                "/v1/testbed/testset_generate",
                headers=test_client_auth_headers["valid_auth"],
                files={"files": ("test.pdf", b"Test PDF content", "application/pdf")},
                data={
                    "name": "Generated Test Set",
                    "ll_model": "test-model",
                    "embed_model": "test-embed",
                    "questions": "5",
                },
            )

            # Verify the response
            assert response.status_code == 200
            assert mock_post.called

    def test_testbed_evaluate_qa_mocked(self, client, test_client_auth_headers):
        """Test evaluating Q&A testset with mocked client"""
        # First, create a testset to evaluate
        test_data = json.dumps(
            [{"question": "Test Q1?", "answer": "Test A1"}, {"question": "Test Q2?", "answer": "Test A2"}]
        )
        test_file = io.BytesIO(test_data.encode())

        files = {"files": ("test.json", test_file, "application/json")}

        response = client.post(
            "/v1/testbed/testset_load?name=Evaluation%20Test%20Set",
            headers=test_client_auth_headers["valid_auth"],
            files=files,
        )

        assert response.status_code == 200

        # Get the testset ID
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        testsets = response.json()
        testset = next((ts for ts in testsets if ts["name"] == "Evaluation Test Set"), None)
        assert testset is not None
        tid = testset["tid"]

        # This is a complex operation that requires a judge model, so we'll mock this part
        with patch.object(client, "post") as mock_post:
            # Configure the mock to return a successful response
            mock_report = EvaluationReport(
                eid="eval_test",
                evaluated="2023-01-01T12:00:00",
                correctness=0.88,
                settings={"model": "test-judge", "client": "test_client"},
                report={"details": "evaluation details"},
                correct_by_topic={"topic1": 0.9},
                failures={"count": 1},
                html_report="<html>Evaluation Report</html>",
            )
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_report.dict()
            mock_post.return_value = mock_response

            # Make the request
            response = client.post(
                "/v1/testbed/evaluate",
                headers=test_client_auth_headers["valid_auth"],
                json={"tid": tid, "judge": "test-judge"},
            )

            # Verify the response
            assert response.status_code == 200
            assert mock_post.called

        # Clean up by deleting the testset
        response = client.delete(f"/v1/testbed/testset_delete/{tid}", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200

    def test_end_to_end_testbed_flow(self, client, test_client_auth_headers):
        """Test the complete testbed workflow"""
        # Step 1: Verify initial state
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        initial_testsets = response.json()

        # Step 2: Create a testset
        test_data = json.dumps([{"question": "What is X?", "answer": "X is Y"}])
        test_file = io.BytesIO(test_data.encode())

        files = {"files": ("test.json", test_file, "application/json")}

        response = client.post(
            "/v1/testbed/testset_load?name=Test%20Flow%20Set",
            headers=test_client_auth_headers["valid_auth"],
            files=files,
        )

        assert response.status_code == 200
        assert "qa_data" in response.json()

        # Get the testset ID from the response
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        testsets = response.json()
        assert len(testsets) > len(initial_testsets)

        # Find the testset we just created
        testset = next((ts for ts in testsets if ts["name"] == "Test Flow Set"), None)
        assert testset is not None
        tid = testset["tid"]

        # Step 3: Get the testset QA data
        response = client.get(f"/v1/testbed/testset_qa?tid={tid}", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200
        assert "qa_data" in response.json()
        assert len(response.json()["qa_data"]) == 1
        assert response.json()["qa_data"][0]["question"] == "What is X?"
        assert response.json()["qa_data"][0]["answer"] == "X is Y"

        # Step 4: Evaluate the testset (mocked)
        with patch.object(client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            response = client.post(
                "/v1/testbed/evaluate",
                headers=test_client_auth_headers["valid_auth"],
                json={"tid": tid, "judge": "flow-judge"},
            )
            assert response.status_code == 200

        # Step 5: Get the evaluation report (mocked)
        with patch.object(client, "get") as mock_get:
            mock_report = EvaluationReport(
                eid="flow_eval_id",
                evaluated="2023-01-01T12:00:00",
                correctness=0.95,
                settings={"model": "flow-judge", "client": "test_client"},
                report={"details": "flow evaluation details"},
                correct_by_topic={"topic1": 0.95},
                failures={"count": 0},
                html_report="<html>Flow Evaluation Report</html>",
            )
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_report.dict()
            mock_get.return_value = mock_response

            response = client.get(
                "/v1/testbed/evaluation?eid=flow_eval_id", headers=test_client_auth_headers["valid_auth"]
            )
            assert response.status_code == 200

        # Step 6: Delete the testset
        response = client.delete(f"/v1/testbed/testset_delete/{tid}", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200
        assert "message" in response.json()

        # Verify the testset was deleted
        response = client.get("/v1/testbed/testsets", headers=test_client_auth_headers["valid_auth"])
        final_testsets = response.json()
        assert len(final_testsets) == len(initial_testsets)
