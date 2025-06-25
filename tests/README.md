# AI Optimizer for Apps Tests
<!-- spell-checker:ignore streamlit, venv, setuptools, pytest -->

This directory contains Tests for the AI Optimizer for Apps.  Tests are automatically
run as part of opening a new Pull Requests.  All tests must pass to enable merging.

## Installing Test Dependencies

1. Create and activate a Python Virtual Environment:

   ```bash
   cd src/
   python3.11 -m venv .venv --copies
   source .venv/bin/activate
   pip3.11 install --upgrade pip wheel setuptools
   ```

1. Install the Python modules:

   ```bash
   pip3.11 install -e ".[all-test]"
   source .venv/bin/activate
   ```

## Running Tests

All tests can be run by using the following command from the **project root**:

```bash
pytest tests -v [--log-cli-level=DEBUG]
```

### Server Endpoint Tests

To run the server endpoint tests, use the following command from the **project root**:

```bash
pytest tests/server -v [--log-cli-level=DEBUG]
```

These tests verify the functionality of the endpoints by establishing:
- A real FastAPI server
- A Docker container used for database tests
- Mocks for external dependencies (OCI)

### Streamlit Tests

To run the Streamlit page tests, use the following command from the **project root**:

```bash
pytest tests/client -v [--log-cli-level=DEBUG]
```

These tests verify the functionality of the Streamlit app by establishing:
- A real AI Optimizer API server 
- A Docker container used for database tests

## Test Structure

### Server Endpoint Tests

The server endpoint tests are organized into two classes:
- `TestNoAuthEndpoints`: Tests that verify authentication is required
- `TestEndpoints`: Tests that verify the functionality of the endpoints

### Streamlit Settings Page Tests

The Streamlit settings page tests are organized into two classes:
- `TestFunctions`: Tests for the utility functions
- `TestUI`: Tests for the Streamlit UI components

## Test Environment

The tests use a combination of real and mocked components:
- A real FastAPI server is started for the endpoint tests
- A Docker container is used for database tests
- Streamlit components are tested using the AppTest framework
- External dependencies are mocked where appropriate 
- To see the elements in the page for testing; use: `print([el for el in at.main])`
