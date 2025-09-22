### **Developer Guide: WilmerAI Unit Testing Suite**

This document provides a comprehensive overview of the WilmerAI unit testing suite. Its purpose is to ensure code
quality, prevent regressions, and make development more predictable. All new code should be accompanied by corresponding
unit tests.

Our testing suite is built on the **pytest** framework, a powerful and popular choice in the Python ecosystem. We use it
alongside plugins for mocking (`pytest-mock`) and code coverage (`pytest-cov`).

-----

## 1\. Environment Setup 🛠️

Before running or writing tests, you must install the necessary development dependencies.

### **Dependencies**

The testing requirements are defined in `requirements-test.txt` in the project root.

**`requirements-test.txt`**

```
pytest
pytest-mock
pytest-cov
flask
```

To install them, run the following command from your project's root directory:

```bash
pip install -r requirements-test.txt
```

### **Configuration**

The `pytest.ini` file configures the test runner. It tells pytest that our source code is in the root directory (`.`)
and that all test files are located within the `tests/` directory.

**`pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

-----

## 2\. Directory Structure

The `tests/` directory mirrors the structure of the `Middleware/` source directory. This convention makes it easy to
locate tests corresponding to a specific module.

```plaintext
WilmerAI
│
└─ Tests/           # All tests live here
   ├─ api/           
   │  ├─ handlers/
   │     └─ impl/
   │        ├─ test_ollama_api_handler.py
   │        └─ test_openai_api_handler.py
   │  ├─ test_api_helpers.py
   │  ├─ test_api_server.py      
   │  └─ test_workflow_gateway.py
   ├─ llmapis/      
   │  └─ handlers/
   │     └─ impl/
   │        ├─ test_koboldcpp_api_handler.py
   │        ├─ test_koboldcpp_api_image_specific_handler.py
   │        ├─ test_ollama_chat_api_handler.py
   │        ├─ test_ollama_chat_api_image_specific_handler.py
   │        ├─ test_ollama_generate_api_handler.py
   │        ├─ test_openai_api_handler.py
   │        ├─ test_openai_chat_api_image_specific_handler.py
   │        └─ test_openai_completions_api_handler.py
   │  └─ test_llm_api.py  
   ├─ services/     
   │  ├─ test_llm_dispatch_service.py   
   │  ├─ test_llm_service.py
   │  ├─ test_locking_service.py
   │  ├─ test_prompt_categorization_service.py   
   │  ├─ test_response_builder_service.py       
   │  └─ test_timestamp_service.py
   ├─ utilities/     
   │  ├─ test_config_utils.py   
   │  ├─ test_datetime_utils.py
   │  ├─ test_file_utils.py
   │  ├─ test_hashing_utils.py   
   │  ├─ test_prompt_extraction_utils.py      
   │  ├─ test_prompt_manipulation_utils.py     
   │  ├─ test_prompt_template_utils.py
   │  ├─ test_search_utils.py    
   │  ├─ test_streaming_utils.py      
   │  ├─ test_text_utils.py       
   │  └─ test_vector_db_utils.py   
   └─ conftest.py    # Central fixture configuration
```

-----

## 3\. Core Testing Concepts

Our suite relies on a few key pytest features to create isolated and maintainable tests.

### **Fixtures (`conftest.py`)**

Fixtures are reusable functions that set up a specific state or object for your tests. Our primary fixtures are defined
in `tests/conftest.py` and are available automatically to all tests.

* **`app()`**: Creates and configures a single instance of our Flask application for the entire test session. It ensures
  all API routes are registered before any tests run.
* **`client(app)`**: Uses the `app` fixture to create a Flask test client. This client is the **primary tool** for
  testing our API handlers, as it can simulate HTTP requests (`GET`, `POST`, etc.) without needing to run a live server.

### **Mocking and Patching (`pytest-mock`)**

Unit tests should test one "unit" of code in isolation. To achieve this, we **mock** its dependencies, such as database
calls, file system operations, or calls to other complex services. The `mocker` fixture (from `pytest-mock`) is our tool
for this.

**Key Mocking Strategy:** We mock the "boundaries" of the component being tested.

* For **API Handler tests**, the most important mock is for the `$workflow_gateway.handle_user_prompt()` function. The
  API layer's job is to translate requests and format responses, so we don't need to run the entire workflow engine. We
  patch this function to return predictable data.
* For **Service-level tests**, we mock their specific dependencies. For example, `test_llm_dispatch_service.py` mocks
  prompt utility functions and the underlying `$LlmApiService$` to isolate its own prompt-building logic.

*Example of mocking the workflow gateway in an API test:*

```python
def test_chat_completions_non_streaming(client, mocker):
    # Mock the gateway to return a simple string
    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "This is a test response."

    # Make a simulated POST request
    response = client.post('/v1/chat/completions', json={...})

    # Assert that our mock was called and the response is correct
    mock_handle_prompt.assert_called_once()
    assert response.status_code == 200
```

-----

## 4\. Test File Breakdown

Here is a summary of what each test file is responsible for.

### **`tests/api/`**

* **`handlers/impl/test_openai_api_handler.py` & `test_ollama_api_handler.py`**

    * **Purpose**: To ensure the public-facing API endpoints correctly handle incoming requests, call the backend
      gateway, and format the final response.
    * **Strategy**: These tests use the `client` fixture to make simulated HTTP requests to each endpoint (e.g.,
      `/v1/chat/completions`, `/api/generate`). They test both **streaming** and **non-streaming** behavior by mocking
      the return value of `handle_user_prompt` to be either a generator or a string. They also verify critical
      pre-processing logic.

* **`test_workflow_gateway.py`**

    * **Purpose**: To test the crucial bridge between the API layer and the workflow engine.
    * **Strategy**: It tests the main routing function, `handle_user_prompt`, ensuring it correctly chooses between a
      custom workflow and the standard prompt categorization service.

* **`test_api_helpers.py`**

    * **Purpose**: To test the utility functions in the `api` layer.
    * **Strategy**: Uses parameterized tests (`@pytest.mark.parametrize`) to efficiently test helper functions against
      various input formats.

* **`test_api_server.py`**

    * **Purpose**: To test the logic of the `ApiServer` class itself.
    * **Strategy**: Mocks the file system (`os.walk`) and module importer (`importlib`) to verify that the server
      correctly discovers and loads all API handler classes on startup.

### **`tests/llmapis/`**

* **`test_koboldcpp_api_handler.py`**

    * **Purpose**: To test the handler for the KoboldCpp `generate` and `stream` endpoints.
    * **Strategy**: Verifies correct URL generation for streaming vs. non-streaming. Tests the parsing of KoboldCpp's
      specific SSE message format and non-streaming JSON response. It uses `mocker` to simulate `requests.post` calls
      for end-to-end tests, asserting the correct payload is sent and the response is handled.

* **`test_koboldcpp_api_image_specific_handler.py`**

    * **Purpose**: To test the specialized handler for KoboldCpp's multimodal (image) capabilities.
    * **Strategy**: This is a test of inheritance and modification. It mocks the parent's `_prepare_payload` method to
      ensure the image-specific handler correctly extracts image data from the conversation history and adds it to the
      `gen_input` dictionary *before* calling the parent logic.

* **`test_ollama_chat_api_handler.py`**

    * **Purpose**: To test the handler for Ollama's `/api/chat` endpoint.
    * **Strategy**: Verifies correct URL generation. Tests the unique payload structure for Ollama, which nests
      generation parameters under an `options` key. It also tests parsing of Ollama's line-delimited JSON stream and
      includes parameterized tests for various valid and malformed stream chunks.

* **`test_ollama_chat_api_image_specific_handler.py`**

    * **Purpose**: To test the specialized handler for Ollama's multimodal chat models (like LLaVA).
    * **Strategy**: Focuses entirely on testing the `_build_messages_from_conversation` method. It verifies that
      `images` role messages are correctly removed and their base64 content is attached to the *last* user message in a
      new `images` key, as required by the Ollama API.

* **`test_ollama_generate_api_handler.py`**

    * **Purpose**: To test the handler for Ollama's legacy `/api/generate` endpoint, which takes a single string prompt.
    * **Strategy**: Similar to the Ollama chat handler test, but for the completions-style endpoint. It verifies URL
      generation, payload creation (including `raw=True`), and parsing of the line-delimited JSON stream specific to
      this endpoint.

* **`test_openai_api_handler.py`**

    * **Purpose**: To test the primary handler for OpenAI-compatible `/v1/chat/completions` endpoints.
    * **Strategy**: Verifies correct URL generation. Tests the parsing of standard OpenAI SSE streams and non-streaming
      JSON responses. Uses parameterized tests to ensure graceful handling of malformed or incomplete response data from
      the API.

* **`test_openai_chat_api_image_specific_handler.py`**

    * **Purpose**: To test the specialized handler for OpenAI's vision-capable chat models (e.g., GPT-4 Vision).
    * **Strategy**: Heavily tests the complex logic in `_build_messages_from_conversation`. It verifies the
      transformation of user and `images` messages into OpenAI's multimodal content block format. It includes tests and
      helper methods for handling various image source types: HTTP URLs, file URIs, data URIs, and raw base64 strings.

* **`test_openai_completions_api_handler.py`**

    * **Purpose**: To test the handler for legacy OpenAI-compatible `/v1/completions` endpoints.
    * **Strategy**: Verifies the correct URL and payload generation, including logic for optionally omitting the `model`
      key. It tests the parsing logic for both streaming and non-streaming responses from this older API format.

### **`tests/services/`**

* **`test_llm_dispatch_service.py`**

    * **Purpose**: To test the core prompt-building logic that prepares data for an LLM call.
    * **Strategy**: A pure business logic test. It verifies the service correctly handles two major paths: building a
      single flattened string for legacy **Completions** APIs, and assembling a structured message list for modern *
      *Chat Completions** APIs.

* **`test_llm_service.py`**

    * **Purpose**: To verify that the `LlmHandlerService` correctly reads endpoint configuration files to construct and
      initialize `LlmHandler` objects.
    * **Strategy**: Mocks file I/O functions to provide fake config data. It then asserts that the `LlmApiService` and
      `LlmHandler` are instantiated with the correct parameters derived from that config.

* **`test_response_builder_service.py`**

    * **Purpose**: To verify that every API response (both full JSON and streaming chunks) is constructed with the
      correct schema and data.
    * **Strategy**: Straightforward tests that call the service's `build_*` methods with sample data and assert that the
      output dictionaries match the expected API format.

-----

## 5\. How to Run Tests & Check Coverage

To run the entire suite, execute the following command from the **project root directory**:

```bash
pytest --cov=Middleware --cov-report=term-missing
```

* `pytest`: Runs the test discovery and execution.
* `--cov=Middleware`: Specifies that we want to measure code coverage against the `Middleware` source directory.
* `--cov-report=term-missing`: Prints a coverage report to the console after the tests finish, highlighting the specific
  line numbers that were **not** executed.

This report is your best tool for identifying parts of the code that still need tests. Aim for high coverage on all new
logic you add.

-----

## 6\. Writing a New Test: A Quick Guide

Let's say you've added a new endpoint: `/v1/my_new_endpoint` in a new handler file. Here’s how you would test it.

1. **Create the Test File**: Create a new file in the corresponding `tests/` directory (e.g.,
   `tests/api/handlers/impl/test_my_new_handler.py`).

2. **Write the Test Function**: Define a test function that accepts the `client` and `mocker` fixtures.

3. **Mock Dependencies**: Patch the `handle_user_prompt` function within your new handler's namespace. Define what it
   should return for this test case.

4. **Make the Request**: Use the `client` to make a `POST` or `GET` request to your new endpoint, including any
   necessary JSON payload.

5. **Assert the Results**: Check that the response status code is correct (e.g., `200`). Verify that the response data (
   e.g., `response.json()`) is what you expect. Finally, assert that your mocked functions were called with the correct
   arguments.

**Example Template:**

```python
# In tests/api/handlers/impl/test_my_new_handler.py

def test_my_new_endpoint_success(client, mocker):
    # 1. Mock the backend gateway to provide a predictable return value
    mock_gateway = mocker.patch('Middleware.api.handlers.impl.my_new_handler.handle_user_prompt')
    mock_gateway.return_value = "Backend processed the request"

    # 2. Define the request payload
    payload = {"input": "some data"}

    # 3. Make the simulated request to your new endpoint
    response = client.post('/v1/my_new_endpoint', json=payload)

    # 4. Assert the outcome
    assert response.status_code == 200
    assert response.json()["data"] == "Backend processed the request"

    # 5. Verify the backend was called correctly
    mock_gateway.assert_called_once()
```