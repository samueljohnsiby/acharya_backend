import pytest
from fastapi.testclient import TestClient
from main import app, get_api_key
from firebase_admin import auth
import time
from unittest.mock import patch

client = TestClient(app)

@pytest.fixture
def mocked_firebase():
    """Mock Firebase admin SDK."""
    with patch("firebase_admin.auth.verify_id_token") as mock_verify_id_token:
        mock_verify_id_token.return_value = {"uid": "test_user_id"}
        yield mock_verify_id_token

@pytest.fixture
def mocked_firestore():
    """Mock Firestore."""
    with patch("firebase_admin.firestore.client") as mock_firestore_client:
        mock_firestore = mock_firestore_client.return_value
        mock_firestore.collection.return_value.document.return_value.get.return_value.exists = False
        yield mock_firestore

@pytest.fixture
def mocked_google_genai():
    """Mock Google Generative AI."""
    with patch("google.generativeai.GenerativeModel.start_chat") as mock_genai_chat:
        mock_chat = mock_genai_chat.return_value
        mock_chat.send_message.return_value.text = "This is a generated response."
        yield mock_genai_chat

def test_signup_success():
    """Test user signup."""
    response = client.post("/signup", json={"email": "test@example.com", "password": "password123"})
    assert response.status_code == 200
    assert "uid" in response.json()

def test_signup_failure():
    """Test signup failure."""
    with patch("firebase_admin.auth.create_user") as mock_create_user:
        mock_create_user.side_effect = Exception("User creation failed")
        response = client.post("/signup", json={"email": "bad@example.com", "password": "short"})
        assert response.status_code == 400
        assert response.json()["detail"] == "User creation failed"

@pytest.mark.asyncio
async def test_login_success(mocked_firebase):
    """Test login success with valid token."""
    response = client.post("/login", headers={"Authorization": "Bearer valid_token"})
    assert response.status_code == 200
    assert response.json() == {"message": "User logged in successfully", "uid": "test_user_id"}

@pytest.mark.asyncio
async def test_login_failure():
    """Test login failure with invalid token."""
    with patch("firebase_admin.auth.verify_id_token", side_effect=Exception("Invalid token")):
        response = client.post("/login", headers={"Authorization": "Bearer invalid_token"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid token"

@pytest.mark.asyncio
async def test_chat_endpoint(mocked_firebase, mocked_firestore, mocked_google_genai):
    """Test chat functionality with a valid session."""
    response = client.post(
        "/chat",
        json={"prompt": "Tell me about algorithms.", "session_id": "1", "user_id": "test_user_id"},
        headers={"X-API-Key": "valid_token"}
    )
    assert response.status_code == 200
    assert "response" in response.json()
    assert response.json()["response"] == "This is a generated response."

@pytest.mark.asyncio
async def test_rate_limiting():
    """Test rate-limiting functionality."""
    # Simulate a burst of requests
    for _ in range(20):
        response = client.get("/chat", headers={"X-API-Key": "valid_token"})
        assert response.status_code != 429
    
    # The next request should trigger rate-limiting
    response = client.get("/chat", headers={"X-API-Key": "valid_token"})
    assert response.status_code == 429
    assert response.json()["detail"] == "Too Many Requests"

@pytest.mark.asyncio
async def test_store_chat_data(mocked_firestore):
    """Test storing chat data in Firestore."""
    response = await store_chat_data(UserChatData(user_id="test_user_id", prompt="Explain AI", session_id="123"))
    assert response["message"] == "Chat data stored/updated successfully"

