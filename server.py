from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Ensure upload directories exist
(ROOT_DIR / "uploads").mkdir(exist_ok=True)
(ROOT_DIR / "uploads" / "notes").mkdir(exist_ok=True)

# Mount static files for uploads
app.mount("/uploads", StaticFiles(directory=str(ROOT_DIR / "uploads")), name="uploads")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Import routes from routes.py, lms_routes.py, and auth_routes.py
from routes import router as app_router
from lms_routes import router as lms_router
from auth_routes import router as auth_router
from teacher_routes import router as teacher_router
from admin_routes import router as admin_router
from blog_routes import router as blog_router
from jobs_routes import router as jobs_router

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Japanese Ninjas API - Ready to help you master Japanese!"}

# Include application routes
api_router.include_router(app_router)
api_router.include_router(lms_router, prefix="/lms")
api_router.include_router(auth_router)
api_router.include_router(teacher_router, prefix="/teacher")
api_router.include_router(admin_router, prefix="/admin")
api_router.include_router(blog_router, prefix="/blog")
api_router.include_router(jobs_router, prefix="/jobs")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()