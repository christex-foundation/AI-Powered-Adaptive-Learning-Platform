from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from contextlib import asynccontextmanager
import json
import os
import asyncio

# Import your RAG system - CRITICAL: Make sure these imports work
try:
    from rag import generate_lesson, Pace, load_subject_components, RAG_COMPONENTS, initialize_hf_llm
    from dataLoading import get_available_subjects, AVAILABLE_SUBJECTS
    print("✓ Successfully imported RAG and DataLoading modules")
except ImportError as e:
    print(f"✗ IMPORT ERROR: {e}")
    raise

# Pydantic models
class LessonRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    sss_level: Literal["SSS 1", "SSS 2", "SSS 3"]
    learning_pace: Literal["low", "moderate", "advance"]


class LessonResponse(BaseModel):
    subject: str
    topic: str
    sss_level: str
    learning_pace: str
    lesson_notes: str
    status: str = "success"


class StatusResponse(BaseModel):
    available_subjects: List[str]
    initialized_subjects: List[str]
    ready: bool


# Lifespan startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 80)
    print("🇸🇱 SSS AI Tutor API Starting...")
    print("=" * 80)
    print(f"✓ {len(AVAILABLE_SUBJECTS)} subject(s) discovered: {', '.join(AVAILABLE_SUBJECTS)}")
    print("ℹ️  Vectorstores load on first request (lazy loading)")
    print("=" * 80)

    try:
        initialize_hf_llm()
        print("✓ LLM initialized successfully")
    except Exception as e:
        print(f"⚠️  LLM initialization failed: {e}")
        import traceback
        traceback.print_exc()

    yield

    print("=" * 80)
    print("🛑 API Shutdown Complete.")
    print("=" * 80)


# Initialize FastAPI
app = FastAPI(
    title="SSS AI Tutor API",
    description="AI-powered personalized lessons for SSS curriculum",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ ENDPOINTS ============

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "SSS AI Tutor API",
        "status": "running",
        "subjects": AVAILABLE_SUBJECTS,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "message": "Server is running"}


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current status"""
    initialized = [s for s in AVAILABLE_SUBJECTS if s in RAG_COMPONENTS]
    return StatusResponse(
        available_subjects=AVAILABLE_SUBJECTS,
        initialized_subjects=initialized,
        ready=True
    )


@app.post("/lesson", response_model=LessonResponse)
async def create_lesson(request: LessonRequest):
    """Generate a personalized lesson"""
    
    # Validate subject
    if request.subject not in AVAILABLE_SUBJECTS:
        raise HTTPException(
            status_code=404,
            detail=f"Subject '{request.subject}' not found. Available: {', '.join(AVAILABLE_SUBJECTS)}"
        )

    # Lazy load subject if needed
    if request.subject not in RAG_COMPONENTS:
        print(f"⚡ Lazy loading subject: {request.subject}")
        try:
            # FIXED: Only pass subject_name, not LLM (it uses global LLM now)
            success = await asyncio.to_thread(
                load_subject_components, 
                request.subject
            )
            if not success:
                raise Exception(f"Failed to initialize {request.subject}")
        except Exception as e:
            import traceback
            print(f"❌ Error during lazy loading: {e}")
            traceback.print_exc()
            raise HTTPException(
                status_code=503,
                detail=f"Could not initialize '{request.subject}': {str(e)}"
            )

    print(f"📝 Generating lesson: {request.subject} - {request.topic} ({request.sss_level}, {request.learning_pace})")

    try:
        # Generate lesson (blocking call in thread)
        lesson_text = await asyncio.to_thread(
            generate_lesson,
            request.subject,
            request.topic,
            request.sss_level,
            request.learning_pace
        )
        
        # Return the actual lesson text
        return LessonResponse(
            subject=request.subject,
            topic=request.topic,
            sss_level=request.sss_level,
            learning_pace=request.learning_pace,
            lesson_notes=lesson_text if lesson_text else "Lesson generation completed. Check server logs.",
            status="success"
        )

    except Exception as e:
        print(f"❌ Error during lesson generation: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lesson generation failed: {str(e)}")


@app.get("/topics")
async def get_topics():
    """Get example topics for each subject"""
    return {
        "Mathematics": [
            "Quadratic Equations",
            "Trigonometry",
            "Vectors",
            "Algebra",
            "Geometry"
        ],
        "English": [
            "Formal Letter Writing",
            "Poetry Analysis",
            "Comprehension",
            "Grammar"
        ],
        "Science": [
            "Force and Motion",
            "Electricity",
            "Chemical Reactions",
            "Photosynthesis"
        ]
    }


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 80)
    print("🚀 Starting SSS AI Tutor API")
    print("=" * 80)
    print("📖 Swagger Docs: http://localhost:8000/docs")
    print("📝 ReDoc: http://localhost:8000/redoc")
    print("✅ Status: http://localhost:8000/status")
    print("=" * 80 + "\n")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=False
    )