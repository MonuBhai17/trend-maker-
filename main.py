from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
from typing import Optional, List

app = FastAPI(title="AnimeShorts API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


class CreateJobRequest(BaseModel):
    video_path: str
    filename: str


class CompleteJobRequest(BaseModel):
    output_path: str
    output_url: str
    clips: List[dict]
    summary: str


class FailJobRequest(BaseModel):
    error: str


@app.get("/")
def root():
    return {"status": "AnimeShorts API running"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/upload-url")
async def get_upload_url(filename: str, content_type: str = "video/mp4"):
    """Frontend calls this to get a presigned URL for direct-to-Supabase upload."""
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "mp4"
    path = f"videos/{uuid.uuid4()}.{ext}"
    try:
        result = supabase.storage.from_("anime-videos").create_signed_upload_url(path)
        return {
            "upload_url": result["signedURL"],
            "path": path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/jobs")
async def create_job(data: CreateJobRequest):
    """Create a new processing job after video is uploaded."""
    job_id = str(uuid.uuid4())
    try:
        video_url = supabase.storage.from_("anime-videos").get_public_url(data.video_path)
        # For private buckets, create a signed read URL valid for 24 hours
        signed_read = supabase.storage.from_("anime-videos").create_signed_url(
            data.video_path, 86400
        )
        actual_url = signed_read.get("signedURL") or video_url

        supabase.table("jobs").insert({
            "id": job_id,
            "video_path": data.video_path,
            "video_url": actual_url,
            "filename": data.filename,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()

        return {"job_id": job_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/pending")
async def get_pending_jobs():
    """Colab worker polls this to find jobs to process."""
    try:
        result = (
            supabase.table("jobs")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .limit(1)
            .execute()
        )
        return result.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Frontend polls this for job status."""
    try:
        result = (
            supabase.table("jobs")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Job not found")
        return result.data
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")


@app.post("/jobs/{job_id}/start")
async def start_job(job_id: str):
    supabase.table("jobs").update({
        "status": "processing",
        "started_at": datetime.utcnow().isoformat()
    }).eq("id", job_id).execute()
    return {"ok": True}


@app.post("/jobs/{job_id}/complete")
async def complete_job(job_id: str, data: CompleteJobRequest):
    supabase.table("jobs").update({
        "status": "completed",
        "output_path": data.output_path,
        "output_url": data.output_url,
        "clips": data.clips,
        "summary": data.summary,
        "completed_at": datetime.utcnow().isoformat()
    }).eq("id", job_id).execute()
    return {"ok": True}


@app.post("/jobs/{job_id}/fail")
async def fail_job(job_id: str, data: FailJobRequest):
    supabase.table("jobs").update({
        "status": "failed",
        "error": data.error,
        "completed_at": datetime.utcnow().isoformat()
    }).eq("id", job_id).execute()
    return {"ok": True}
