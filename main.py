from fastapi import FastAPI, Depends, HTTPException
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

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "https://socraticbot-4bc8c.web.app",
    ],  # Replace with your Angular app's URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure the Google AI SDK with the API key
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Dictionary to store chat sessions for different users or clients
chat_sessions = {}

# Initialize Firebase Admin SDK
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

# Define the message model
class Message(BaseModel):
    prompt: str
    session_id: str = None
    user_id: str = None

# Define the API key header
api_key_header = APIKeyHeader(name="X-API-Key")

# Dependency for API key verification
async def get_api_key(x_api_key: str = Depends(api_key_header)):
    stored_api_key = os.getenv("API_KEY")
    if x_api_key != stored_api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

# Function to read file content
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

# Store chat data in Firestore
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
            chat_sessions[message.session_id] = chat_session

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

# OAuth2 scheme for the token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Login endpoint for token verification
@app.post("/login")
async def login(token: str = Depends(oauth2_scheme)):
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        return {"message": "User logged in successfully", "uid": uid}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")

# User signup endpoint
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
