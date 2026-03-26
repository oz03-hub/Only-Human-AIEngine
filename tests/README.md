# AIEngine Test Suite

Comprehensive test suite for the UMass AIEngine facilitation system.

## Test Coverage

### Pipeline Tests (`test_pipeline.py`)
Tests the core facilitation decision pipeline:
- **Retry mechanism**: Exponential backoff for LLM failures
- **Stage 1**: Temporal feature extraction and Random Forest classification
- **Stage 2**: LLM verification with mocked API calls
- **Stage 3**: Facilitation message generation
- **Complete pipeline**: Full flow with early termination logic
- **Feature extraction**: Temporal features from conversation history

### Facilitation Service Tests (`test_facilitation_service.py`)
Tests the facilitation orchestration service:
- Single thread facilitation checks
- Multiple thread processing
- Insufficient message handling
- Facilitation log creation
- Thread-specific queries
- Error handling for nonexistent groups

### Webhook Client Tests (`test_webhook_client.py`)
Tests the external API callback client:
- Successful response sending
- Empty response handling
- Retry logic on server errors (5xx)
- No retry on client errors (4xx)
- Network error handling
- Max retries exceeded scenarios
- Request validation and headers

### API Integration Tests (`test_api.py`)
Tests FastAPI endpoints end-to-end:
- **Webhook endpoint**: Message storage and background facilitation
- **Group activity**: Updating group status
- **Message logs**: Retrieving conversation history
- Authentication and validation
- Multiple groups and questions handling

### Deployment Smoke Tests (`smoke_test.py`)
Runs against a live deployed instance (e.g. Cloud Run) to verify:
- Root and health endpoints respond correctly
- API key authentication rejects unauthorized requests
- Invalid payloads return 422 (not 500)
- Webhook stores data and it can be read back via `/logs`
- Group activity status can be toggled

## Running Tests

### Run all tests:
```bash
source .venv/bin/activate
pytest tests/
```

### Run specific test file:
```bash
pytest tests/test_pipeline.py -v
```

### Run specific test:
```bash
pytest tests/test_pipeline.py::TestFacilitationPipeline::test_complete_pipeline_with_facilitation -v
```

### Run with coverage:
```bash
pytest tests/ --cov=app --cov-report=html
```

### Run only fast tests (skip integration):
```bash
pytest tests/ -m "not integration"
```

### Run smoke tests against a deployment:
```bash
python tests/smoke_test.py --url https://your-cloud-run-url --api-key YOUR_API_KEY
```

You can also set a custom timeout (default 30s):
```bash
python tests/smoke_test.py --url https://your-cloud-run-url --api-key YOUR_API_KEY --timeout 60
```

The script exits with code 0 if all tests pass and code 1 if any fail, so it works in CI/CD pipelines (e.g. as a Cloud Build step after deploy).

## Test Fixtures

### Database Fixtures (`conftest.py`)
- `db_engine`: In-memory SQLite database
- `db_session`: Async database session
- `test_group`: Sample group
- `test_user`: Sample user
- `test_question`: Sample question
- `test_group_question`: Sample thread
- `test_messages`: Sample conversation messages

### Mock Fixtures
- `mock_llm_verification_response`: Stage 2 LLM response
- `mock_llm_generation_response`: Stage 3 LLM response
- `mock_llm_no_facilitation_response`: Negative LLM response

## Test Configuration

See `pytest.ini` for:
- Test discovery patterns
- Async test mode
- Output formatting
- Logging configuration

## Writing New Tests

### Example test structure:
```python
import pytest
import pytest_asyncio
from app.services.your_service import YourService

class TestYourService:
    """Test your service."""

    @pytest_asyncio.fixture
    async def your_service(self, db_session):
        """Create service instance."""
        return YourService(db_session)

    @pytest.mark.asyncio
    async def test_your_feature(self, your_service):
        """Test a specific feature."""
        result = await your_service.do_something()
        assert result == expected_value
```

### Best Practices:
1. Use descriptive test names that explain what is being tested
2. Test both success and failure cases
3. Mock external dependencies (LLM API, external webhooks)
4. Use fixtures to avoid code duplication
5. Keep tests isolated and independent
6. Test edge cases and error conditions

## Continuous Integration

Tests run automatically on:
- Pull requests
- Main branch commits
- Pre-deployment checks

All tests must pass before merging code.
