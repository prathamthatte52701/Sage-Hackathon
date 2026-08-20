from fastapi.exceptions import RequestValidationError
import pytest

from main import validation_exception_handler


@pytest.mark.asyncio
async def test_validation_error_shape():
    response = await validation_exception_handler(None, RequestValidationError([]))
    assert response.status_code == 422
