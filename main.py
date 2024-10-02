from fastapi import FastAPI, Depends, HTTPException,Request
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pydantic import BaseModel
import os
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi.security import APIKeyHeader
from fastapi.security import OAuth2PasswordBearer
import firebase_admin
from firebase_admin import auth, credentials, firestore
import json
import time
from collections import defaultdict

# Load environment variables
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "https://socraticbot-4bc8c.web.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure the Google AI SDK with the API key
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Dictionary to store chat sessions for different users or clients
chat_sessions = {}

# OAuth2 scheme for the token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Initialize Firebase Admin SDK
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

# Rate limit configuration
RATE_LIMIT = 20  # Max requests
TIME_WINDOW = 60  # In seconds
requests = defaultdict(list)  # Store request timestamps per client IP

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host
    current_time = time.time()

    # Clean up old timestamps
    requests[client_ip] = [timestamp for timestamp in requests[client_ip] if current_time - timestamp < TIME_WINDOW]

    # Check if the client has exceeded the rate limit
    if len(requests[client_ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too Many Requests")

    # Add current request timestamp
    requests[client_ip].append(current_time)

    response = await call_next(request)
    return response

# Define the message model
class Message(BaseModel):
    prompt: str
    session_id: str = None
    user_id: str = None

# Define the API key header
api_key_header = APIKeyHeader(name="X-API-Key")

# Dependency for API key verification
async def get_api_key(x_api_key: str = Depends(api_key_header)):
    try:
        decoded_token = auth.verify_id_token(x_api_key)
        uid = decoded_token['uid']
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e
    return x_api_key

async def read_file(file_path: str) -> str:
    try:
        with open(file_path, 'r') as file:
            content = file.read()
        return content
    except FileNotFoundError:
        return "File not found."
    except Exception as e:
        return f"An error occurred: {e}"

# Define User data to store in Firestore
class UserChatData(BaseModel):
    user_id: str
    prompt: str
    session_id: str

async def store_chat_data(user_data: UserChatData):
    try:
        doc_ref = db.collection('user_chats').document(user_data.user_id)
        doc = doc_ref.get()

        if doc.exists:
            existing_data = doc.to_dict()
            updated_sessions = existing_data.get("sessions", [])
            updated_sessions.append({
                "session_id": user_data.session_id,
                "prompt": user_data.prompt
            })
            doc_ref.update({"sessions": updated_sessions})
        else:
            doc_ref.set({
                "user_id": user_data.user_id,
                "sessions": [{
                    "session_id": user_data.session_id,
                    "prompt": user_data.prompt
                }]
            })
        
        return {"message": "Chat data stored/updated successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error storing chat data: {e}")

# Chat endpoint with API key verification
@app.post("/chat")
async def chat(message: Message, api_key: str = Depends(get_api_key)):
    try:
        generation_config = {
            "temperature": 0.0,
            "top_p": 0.95,
            "top_k": 64,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }

        content = await read_file('example.txt')

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        }

        if message.session_id and message.session_id in chat_sessions:
            chat_session = chat_sessions[message.session_id]
        else:
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                generation_config=generation_config,
                system_instruction=f"""
                You are a Socratic teacher, guiding students to understand complex topics through a series of thought-provoking questions. 
                Your goal is to break down their questions into smaller, manageable parts, encouraging them to critically analyze and think. 
                Use stories or quotes to keep them engaged and make them think. Suggest good books and resources but avoid providing links.
                Don't give direct answers unless there's significant confusion or frustration. Offer hints and keep them engaged.
                Refer following examples for guidance
                {content}
                """,
                safety_settings=safety_settings
            )
            chat_session = model.start_chat()
            session_id = str(len(chat_sessions) + 1)
            chat_sessions[session_id] = chat_session
            message.session_id = session_id

        response = chat_session.send_message(message.prompt)

        user_data = UserChatData(
            user_id=message.user_id,
            prompt=message.prompt,
            session_id=message.session_id
        )
        await store_chat_data(user_data)

        return {"response": response.text, "session_id": message.session_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login")
async def login(token: str = Depends(oauth2_scheme)):
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        return {"message": "User logged in successfully", "uid": uid}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")

class UserCreate(BaseModel):
    email: str
    password: str

@app.post('/signup')
async def signup(user: UserCreate):
    try:
        user_record = auth.create_user(
            email=user.email,
            password=user.password
        )
        return {"message": "User created successfully", "uid": user_record.uid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
