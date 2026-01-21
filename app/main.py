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
from app.kamiwaza_provisioner import KamiwazaProvisioner
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
    title="Kamiwaza Deployment Manager",
    description="Provision Kamiwaza users, deploy Kaizen instances, and manage EC2 infrastructure",
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
    deployment_type: str = Form("docker"),
    kamiwaza_branch: Optional[str] = Form("release/0.9.2"),
    kamiwaza_github_token: Optional[str] = Form(None),
    aws_region: str = Form(...),
    vpc_id: Optional[str] = Form(None),
    subnet_id: Optional[str] = Form(None),
    security_group_ids: Optional[str] = Form(None),
    key_pair_name: Optional[str] = Form(None),
    instance_type: str = Form(...),
    volume_size_gb: int = Form(30),
    ami_id: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    dockerhub_images: Optional[str] = Form(None),
    requester_email: str = Form(...),
    csv_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Create a new provisioning job"""

    # Verify CSRF token
    if not csrf_protection.verify_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    try:
        # Parse Docker containers (only required for docker deployment type)
        containers = []
        if deployment_type == "docker":
            if not dockerhub_images:
                raise HTTPException(status_code=400, detail="dockerhub_images is required for docker deployment type")
            try:
                dockerhub_images_list = json.loads(dockerhub_images)
                containers = [ContainerConfig(**c) for c in dockerhub_images_list]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid dockerhub_images format: {str(e)}")
        elif deployment_type == "kamiwaza":
            # For Kamiwaza, docker images are not required (will be auto-configured)
            containers = []

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

        # AWS auth settings from config (configured in Settings page or .env)
        aws_auth_method = settings.aws_auth_method
        assume_role_arn = settings.aws_assume_role_arn
        external_id = settings.aws_external_id
        session_name = settings.aws_session_name

        # Create job data
        job_data = JobCreate(
            job_name=job_name,
            deployment_type=deployment_type,
            kamiwaza_branch=kamiwaza_branch,
            kamiwaza_github_token=kamiwaza_github_token,
            aws_region=aws_region,
            aws_auth_method=aws_auth_method,
            assume_role_arn=assume_role_arn,
            external_id=external_id,
            session_name=session_name,
            access_key=None,
            secret_key=None,
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
            deployment_type=job_data.deployment_type,
            kamiwaza_branch=job_data.kamiwaza_branch,
            kamiwaza_github_token=job_data.kamiwaza_github_token,
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
            dockerhub_images=[c.model_dump() for c in job_data.dockerhub_images] if job_data.dockerhub_images else [],
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


# ============================================================================
# DEPLOYMENT MANAGER ROUTES (Kamiwaza User Provisioning)
# ============================================================================

@app.get("/deployment-manager", response_class=HTMLResponse)
async def deployment_manager_home(
    request: Request
):
    """Display Deployment Manager CSV upload form"""
    csrf_token = csrf_protection.generate_token()

    return templates.TemplateResponse("deployment_manager.html", {
        "request": request,
        "csrf_token": csrf_token
    })


@app.post("/deployment-manager/provision")
async def create_provisioning_job(
    request: Request,
    csrf_token: str = Form(...),
    csv_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Create a new Kamiwaza provisioning job"""

    # Verify CSRF token
    if not csrf_protection.verify_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    try:
        # Read CSV content
        csv_content = await csv_file.read()

        # Validate CSV
        provisioner = KamiwazaProvisioner()
        is_valid, users, errors = provisioner.validate_csv(csv_content)

        if not is_valid:
            error_msg = "CSV validation failed:\n" + "\n".join(errors)
            raise HTTPException(status_code=400, detail=error_msg)

        # Create job in database
        job = Job(
            job_name=f"Kamiwaza User Provisioning - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            status="pending",
            aws_region="N/A",  # Not used for Kamiwaza provisioning
            aws_auth_method="N/A",
            instance_type="N/A",
            volume_size_gb=0,
            requester_email="deployment-manager@kamiwaza.local",
            users_data=users  # Store users for display
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        # Save CSV file
        file_path = Path("uploads") / f"kamiwaza_job_{job.id}_{csv_file.filename}"
        with open(file_path, "wb") as f:
            f.write(csv_content)

        # Create file record
        job_file = JobFile(
            job_id=job.id,
            filename=csv_file.filename,
            file_type="csv",
            file_path=str(file_path),
            file_size=len(csv_content)
        )
        db.add(job_file)
        job.csv_file_id = job_file.id
        db.commit()

        # Log job creation
        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"Provisioning job created with {len(users)} user(s)",
            source="deployment-manager"
        )
        db.add(log)
        db.commit()

        return RedirectResponse(url=f"/deployment-manager/{job.id}", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating provisioning job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")


@app.get("/deployment-manager/{job_id}", response_class=HTMLResponse)
async def deployment_manager_progress(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db)
):
    """Display provisioning progress"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    logs = db.query(JobLog).filter(JobLog.job_id == job_id).order_by(JobLog.timestamp.desc()).limit(200).all()
    csrf_token = csrf_protection.generate_token()

    return templates.TemplateResponse("deployment_progress.html", {
        "request": request,
        "job": job,
        "logs": logs,
        "csrf_token": csrf_token
    })


@app.post("/deployment-manager/{job_id}/run")
async def run_provisioning_job(
    job_id: int,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db)
):
    """Start provisioning job execution"""

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
        message="Provisioning job queued for execution",
        source="deployment-manager"
    )
    db.add(log)
    db.commit()

    # Enqueue Celery task
    try:
        from worker.tasks import execute_kamiwaza_provisioning
        execute_kamiwaza_provisioning.delay(job_id)
    except Exception as e:
        logger.error(f"Failed to enqueue provisioning job: {str(e)}")
        job.status = "failed"
        job.error_message = f"Failed to enqueue: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to enqueue job")

    return RedirectResponse(url=f"/deployment-manager/{job_id}", status_code=303)


@app.get("/api/deployment-manager/{job_id}/logs")
async def get_provisioning_logs(
    job_id: int,
    after: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get provisioning job logs (for polling/live updates)"""
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


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request
):
    """Display configuration settings page"""
    csrf_token = csrf_protection.generate_token()

    # Read current configuration from settings
    config = {
        "KAMIWAZA_URL": settings.kamiwaza_url,
        "KAMIWAZA_USERNAME": settings.kamiwaza_username,
        "KAMIWAZA_PASSWORD": settings.kamiwaza_password,
        "KAMIWAZA_DB_PATH": settings.kamiwaza_db_path,
        "KAMIWAZA_PACKAGE_URL": settings.kamiwaza_package_url,
        "KAMIWAZA_PROVISION_SCRIPT": settings.kamiwaza_provision_script,
        "KAIZEN_SOURCE": settings.kaizen_source,
        "DEFAULT_USER_PASSWORD": settings.default_user_password,
        "AWS_AUTH_METHOD": settings.aws_auth_method,
        "AWS_ASSUME_ROLE_ARN": settings.aws_assume_role_arn,
        "AWS_EXTERNAL_ID": settings.aws_external_id,
        "AWS_SESSION_NAME": settings.aws_session_name,
        "AWS_ACCESS_KEY_ID": settings.aws_access_key_id,
        "AWS_SECRET_ACCESS_KEY": settings.aws_secret_access_key,
        "AWS_SSO_PROFILE": settings.aws_sso_profile,
        "AWS_PROVISIONING_METHOD": settings.aws_provisioning_method,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "N2YO_API_KEY": settings.n2yo_api_key,
        "DATALASTIC_API_KEY": settings.datalastic_api_key,
        "FLIGHTRADAR24_API_KEY": settings.flightradar24_api_key,
    }

    # Check if base AWS credentials are available
    from app.aws_cdk_provisioner import AWSCDKProvisioner
    provisioner = AWSCDKProvisioner()
    credentials_available, credentials_message = provisioner.check_base_credentials()

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "csrf_token": csrf_token,
        "config": config,
        "aws_credentials_available": credentials_available,
        "aws_credentials_message": credentials_message
    })


@app.post("/settings")
async def save_settings(
    request: Request,
    csrf_token: str = Form(...),
    kamiwaza_url: str = Form(...),
    kamiwaza_username: str = Form(...),
    kamiwaza_password: str = Form(...),
    kamiwaza_db_path: str = Form(""),
    kamiwaza_package_url: str = Form(...),
    provision_script: str = Form(...),
    kaizen_source: str = Form(...),
    default_user_password: str = Form(...),
    aws_auth_method: str = Form("assume_role"),
    aws_assume_role_arn: str = Form(""),
    aws_external_id: str = Form(""),
    aws_session_name: str = Form("kamiwaza-provisioner"),
    aws_access_key_id: str = Form(""),
    aws_secret_access_key: str = Form(""),
    aws_sso_profile: str = Form(""),
    aws_provisioning_method: str = Form("cdk"),
    anthropic_api_key: str = Form(""),
    n2yo_api_key: str = Form(""),
    datalastic_api_key: str = Form(""),
    flightradar24_api_key: str = Form("")
):
    """Save configuration settings to .env file"""

    # Verify CSRF
    if not csrf_protection.verify_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    try:
        # Build .env content
        env_content = f"""# Kamiwaza Deployment Manager Configuration
# Generated: {datetime.utcnow().isoformat()}

# Kamiwaza Connection
KAMIWAZA_URL={kamiwaza_url}
KAMIWAZA_USERNAME={kamiwaza_username}
KAMIWAZA_PASSWORD={kamiwaza_password}
KAMIWAZA_DB_PATH={kamiwaza_db_path}

# Kamiwaza Package
KAMIWAZA_PACKAGE_URL={kamiwaza_package_url}

# Script Paths
KAMIWAZA_PROVISION_SCRIPT={provision_script}
KAIZEN_SOURCE={kaizen_source}

# User Credentials
DEFAULT_USER_PASSWORD={default_user_password}

# AWS Authentication
# Note: AWS Region is specified per-job, not here
AWS_AUTH_METHOD={aws_auth_method}
AWS_ASSUME_ROLE_ARN={aws_assume_role_arn}
AWS_EXTERNAL_ID={aws_external_id}
AWS_SESSION_NAME={aws_session_name}
AWS_ACCESS_KEY_ID={aws_access_key_id}
AWS_SECRET_ACCESS_KEY={aws_secret_access_key}
AWS_SSO_PROFILE={aws_sso_profile}
AWS_PROVISIONING_METHOD={aws_provisioning_method}

# API Keys
ANTHROPIC_API_KEY={anthropic_api_key}
N2YO_API_KEY={n2yo_api_key}
DATALASTIC_API_KEY={datalastic_api_key}
FLIGHTRADAR24_API_KEY={flightradar24_api_key}

# Database
DATABASE_URL=sqlite:///./app.db

# Redis
REDIS_URL=redis://localhost:6379/0
"""

        # Write to .env file
        with open(".env", "w") as f:
            f.write(env_content)

        # Update environment variables in current process
        os.environ["KAMIWAZA_URL"] = kamiwaza_url
        os.environ["KAMIWAZA_USERNAME"] = kamiwaza_username
        os.environ["KAMIWAZA_PASSWORD"] = kamiwaza_password
        os.environ["KAMIWAZA_DB_PATH"] = kamiwaza_db_path
        os.environ["KAMIWAZA_PACKAGE_URL"] = kamiwaza_package_url
        os.environ["KAMIWAZA_PROVISION_SCRIPT"] = provision_script
        os.environ["KAIZEN_SOURCE"] = kaizen_source
        os.environ["DEFAULT_USER_PASSWORD"] = default_user_password
        os.environ["AWS_AUTH_METHOD"] = aws_auth_method
        os.environ["AWS_ASSUME_ROLE_ARN"] = aws_assume_role_arn
        os.environ["AWS_EXTERNAL_ID"] = aws_external_id
        os.environ["AWS_SESSION_NAME"] = aws_session_name
        os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
        os.environ["AWS_SSO_PROFILE"] = aws_sso_profile
        os.environ["AWS_PROVISIONING_METHOD"] = aws_provisioning_method
        os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key
        os.environ["N2YO_API_KEY"] = n2yo_api_key
        os.environ["DATALASTIC_API_KEY"] = datalastic_api_key
        os.environ["FLIGHTRADAR24_API_KEY"] = flightradar24_api_key

        logger.info("Configuration saved successfully")

        # Redirect back to settings with success message
        config = {
            "KAMIWAZA_URL": kamiwaza_url,
            "KAMIWAZA_USERNAME": kamiwaza_username,
            "KAMIWAZA_PASSWORD": kamiwaza_password,
            "KAMIWAZA_DB_PATH": kamiwaza_db_path,
            "KAMIWAZA_PACKAGE_URL": kamiwaza_package_url,
            "KAMIWAZA_PROVISION_SCRIPT": provision_script,
            "KAIZEN_SOURCE": kaizen_source,
            "DEFAULT_USER_PASSWORD": default_user_password,
            "AWS_AUTH_METHOD": aws_auth_method,
            "AWS_ASSUME_ROLE_ARN": aws_assume_role_arn,
            "AWS_EXTERNAL_ID": aws_external_id,
            "AWS_SESSION_NAME": aws_session_name,
            "AWS_ACCESS_KEY_ID": aws_access_key_id,
            "AWS_SECRET_ACCESS_KEY": aws_secret_access_key,
            "AWS_SSO_PROFILE": aws_sso_profile,
            "AWS_PROVISIONING_METHOD": aws_provisioning_method,
            "ANTHROPIC_API_KEY": anthropic_api_key,
            "N2YO_API_KEY": n2yo_api_key,
            "DATALASTIC_API_KEY": datalastic_api_key,
            "FLIGHTRADAR24_API_KEY": flightradar24_api_key,
        }

        csrf_token = csrf_protection.generate_token()

        return templates.TemplateResponse("settings.html", {
            "request": request,
            "csrf_token": csrf_token,
            "config": config,
            "message": "Configuration saved successfully. Changes will take effect for new provisioning jobs.",
            "message_type": "success"
        })

    except Exception as e:
        logger.error(f"Error saving settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {str(e)}")


@app.post("/api/test-kamiwaza-connection")
async def test_kamiwaza_connection(request: Request):
    """Test connection to Kamiwaza"""
    try:
        import httpx

        body = await request.json()
        url = body.get("url")
        username = body.get("username")
        password = body.get("password")

        if not url or not username or not password:
            return JSONResponse({
                "success": False,
                "error": "Missing required parameters"
            })

        # Try to authenticate
        with httpx.Client(verify=False, timeout=10.0) as client:
            auth_response = client.post(
                f"{url}/api/auth/token",
                data={"username": username, "password": password}
            )

            if auth_response.status_code == 200:
                token = auth_response.json().get("access_token")

                # Try to get account info
                try:
                    me_response = client.get(
                        f"{url}/api/auth/me",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    if me_response.status_code == 200:
                        user_info = me_response.json()
                        return JSONResponse({
                            "success": True,
                            "account": user_info.get("username", username)
                        })
                except:
                    pass

                return JSONResponse({
                    "success": True,
                    "account": username
                })
            else:
                return JSONResponse({
                    "success": False,
                    "error": f"Authentication failed: HTTP {auth_response.status_code}"
                })

    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
