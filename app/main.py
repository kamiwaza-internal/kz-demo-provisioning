import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import Job, JobLog, JobFile
from app.schemas import JobCreate, JobResponse, ContainerConfig
from app.auth import csrf_protection
from app.csv_handler import CSVHandler, CSVValidationError
from app.config import settings
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="AWS EC2 Provisioning Service",
    description="Provision EC2 instances with Docker containers using Terraform",
    version="1.0.0"
)

# Initialize templates
templates = Jinja2Templates(directory="app/templates")

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()
    # Create jobs workdir
    Path(settings.jobs_workdir).mkdir(parents=True, exist_ok=True)
    Path("uploads").mkdir(parents=True, exist_ok=True)
    logger.info("Application started successfully")


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    """Dashboard showing all jobs"""
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    csrf_token = csrf_protection.generate_token()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "jobs": jobs,
        "csrf_token": csrf_token
    })


@app.get("/jobs/new", response_class=HTMLResponse)
async def new_job_form(
    request: Request
):
    """Display form to create new job"""
    csrf_token = csrf_protection.generate_token()

    return templates.TemplateResponse("job_new.html", {
        "request": request,
        "csrf_token": csrf_token,
        "allowed_regions": settings.allowed_regions_list,
        "allowed_instance_types": settings.allowed_instance_types_list,
        "allow_access_key_auth": settings.allow_access_key_auth
    })


@app.post("/jobs")
async def create_job(
    request: Request,
    csrf_token: str = Form(...),
    job_name: str = Form(...),
    aws_region: str = Form(...),
    aws_auth_method: str = Form(...),
    assume_role_arn: Optional[str] = Form(None),
    external_id: Optional[str] = Form(None),
    session_name: Optional[str] = Form("terraform-provisioning"),
    access_key: Optional[str] = Form(None),
    secret_key: Optional[str] = Form(None),
    vpc_id: Optional[str] = Form(None),
    subnet_id: Optional[str] = Form(None),
    security_group_ids: Optional[str] = Form(None),
    key_pair_name: Optional[str] = Form(None),
    instance_type: str = Form(...),
    volume_size_gb: int = Form(30),
    ami_id: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    dockerhub_images: str = Form(...),
    requester_email: str = Form(...),
    csv_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Create a new provisioning job"""

    # Verify CSRF token
    if not csrf_protection.verify_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    try:
        # Parse JSON fields
        try:
            dockerhub_images_list = json.loads(dockerhub_images)
            containers = [ContainerConfig(**c) for c in dockerhub_images_list]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid dockerhub_images format: {str(e)}")

        # Parse tags
        tags_dict = {}
        if tags:
            try:
                tags_dict = json.loads(tags)
            except Exception:
                # Try parsing as key=value pairs
                for tag_pair in tags.split(","):
                    if "=" in tag_pair:
                        key, value = tag_pair.split("=", 1)
                        tags_dict[key.strip()] = value.strip()

        # Parse security group IDs
        sg_ids = []
        if security_group_ids:
            sg_ids = [sg.strip() for sg in security_group_ids.split(",") if sg.strip()]

        # Create job data
        job_data = JobCreate(
            job_name=job_name,
            aws_region=aws_region,
            aws_auth_method=aws_auth_method,
            assume_role_arn=assume_role_arn,
            external_id=external_id,
            session_name=session_name,
            access_key=access_key,
            secret_key=secret_key,
            vpc_id=vpc_id,
            subnet_id=subnet_id,
            security_group_ids=sg_ids,
            key_pair_name=key_pair_name,
            instance_type=instance_type,
            volume_size_gb=volume_size_gb,
            ami_id=ami_id,
            tags=tags_dict,
            dockerhub_images=containers,
            requester_email=requester_email
        )

        # Create job in database
        job = Job(
            job_name=job_data.job_name,
            status="pending",
            aws_region=job_data.aws_region,
            aws_auth_method=job_data.aws_auth_method,
            assume_role_arn=job_data.assume_role_arn,
            external_id=job_data.external_id,
            session_name=job_data.session_name,
            vpc_id=job_data.vpc_id,
            subnet_id=job_data.subnet_id,
            security_group_ids=job_data.security_group_ids,
            key_pair_name=job_data.key_pair_name,
            instance_type=job_data.instance_type,
            volume_size_gb=job_data.volume_size_gb,
            ami_id=job_data.ami_id,
            tags=job_data.tags,
            dockerhub_images=[c.model_dump() for c in job_data.dockerhub_images],
            requester_email=job_data.requester_email
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        # Handle CSV file upload
        if csv_file and csv_file.filename:
            try:
                file_content = await csv_file.read()

                # Validate file size
                CSVHandler.validate_file_size(len(file_content))

                # Parse and validate CSV
                parsed_users, warnings = CSVHandler.parse_and_validate(file_content)

                # Save file
                file_path = Path("uploads") / f"job_{job.id}_{csv_file.filename}"
                with open(file_path, "wb") as f:
                    f.write(file_content)

                # Create file record
                job_file = JobFile(
                    job_id=job.id,
                    filename=csv_file.filename,
                    file_type="csv",
                    file_path=str(file_path),
                    file_size=len(file_content)
                )
                db.add(job_file)

                # Update job with users data
                job.csv_file_id = job_file.id
                job.users_data = parsed_users

                db.commit()

                # Log warnings
                for warning in warnings:
                    log = JobLog(
                        job_id=job.id,
                        level="warning",
                        message=warning,
                        source="csv"
                    )
                    db.add(log)

                db.commit()

            except CSVValidationError as e:
                # Delete job and return error
                db.delete(job)
                db.commit()
                raise HTTPException(status_code=400, detail=f"CSV validation error: {str(e)}")

        # Log job creation
        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"Job created",
            source="system"
        )
        db.add(log)
        db.commit()

        return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db)
):
    """Display job details and status"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    logs = db.query(JobLog).filter(JobLog.job_id == job_id).order_by(JobLog.timestamp.desc()).limit(100).all()
    csrf_token = csrf_protection.generate_token()

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job,
        "logs": logs,
        "csrf_token": csrf_token
    })


@app.post("/jobs/{job_id}/run")
async def run_job(
    job_id: int,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db)
):
    """Enqueue job for execution"""

    # Verify CSRF
    if not csrf_protection.verify_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ["pending", "failed"]:
        raise HTTPException(status_code=400, detail=f"Job cannot be run in status: {job.status}")

    # Update status to queued
    job.status = "queued"
    db.commit()

    # Add log
    log = JobLog(
        job_id=job.id,
        level="info",
        message=f"Job queued",
        source="system"
    )
    db.add(log)
    db.commit()

    # Enqueue Celery task
    try:
        from worker.tasks import execute_provisioning_job
        execute_provisioning_job.delay(job_id)
    except Exception as e:
        logger.error(f"Failed to enqueue job: {str(e)}")
        job.status = "failed"
        job.error_message = f"Failed to enqueue: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to enqueue job")

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/api/jobs/{job_id}/logs")
async def get_job_logs(
    job_id: int,
    after: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get job logs (for polling/live updates)"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    query = db.query(JobLog).filter(JobLog.job_id == job_id)

    if after is not None:
        query = query.filter(JobLog.id > after)

    logs = query.order_by(JobLog.timestamp.asc()).all()

    return JSONResponse({
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "level": log.level,
                "message": log.message,
                "source": log.source
            }
            for log in logs
        ],
        "job_status": job.status
    })


@app.get("/api/jobs/{job_id}")
async def get_job_api(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get job details as JSON"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.model_validate(job)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
