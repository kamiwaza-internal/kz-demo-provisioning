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


def get_latest_cached_ami(region: str = "us-east-1") -> Optional[Dict]:
    """Get the latest cached Kamiwaza AMI for a region"""
    try:
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        import boto3
        from botocore.exceptions import ClientError

        # Get credentials
        provisioner = AWSCDKProvisioner()
        auth_method = settings.aws_auth_method

        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = settings.aws_assume_role_arn
                external_id = settings.aws_external_id
                session_name = settings.aws_session_name

                if not role_arn:
                    return None

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=region
                )
            elif auth_method == "access_keys":
                access_key = settings.aws_access_key_id
                secret_key = settings.aws_secret_access_key

                if not access_key or not secret_key:
                    return None

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': region
                }
        except Exception:
            return None

        # List AMIs
        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Get all AMIs owned by self and filter for Kamiwaza AMIs
        # (supports both manual and auto-created AMIs with different tags)
        response = ec2_client.describe_images(
            Filters=[
                {
                    'Name': 'state',
                    'Values': ['available']
                }
            ],
            Owners=['self']
        )

        # Filter for Kamiwaza AMIs (check for either tag scheme)
        amis = []
        for image in response.get('Images', []):
            tags = {tag['Key']: tag['Value'] for tag in image.get('Tags', [])}
            # Check if it's a Kamiwaza AMI (either manually created or auto-created)
            if tags.get('Application') == 'Kamiwaza' or tags.get('ManagedBy') == 'KamiwazaDeploymentManager':
                amis.append(image)
        if not amis:
            return None

        # Sort by creation date (newest first)
        amis.sort(key=lambda x: x.get('CreationDate', ''), reverse=True)

        # Get the latest AMI
        latest_ami = amis[0]
        tags = {tag['Key']: tag['Value'] for tag in latest_ami.get('Tags', [])}

        return {
            'ami_id': latest_ami['ImageId'],
            'name': latest_ami.get('Name', 'Unknown'),
            'version': tags.get('Version', tags.get('KamiwazaVersion', 'Unknown')),
            'creation_date': latest_ami.get('CreationDate', '')
        }

    except Exception as e:
        logger.warning(f"Failed to get cached AMI for region {region}: {str(e)}")
        logger.debug(f"Auth method: {settings.aws_auth_method}, Has credentials: {bool(credentials)}")
        return None


def get_available_amis(region: str = "us-east-1", limit: int = 10) -> List[Dict]:
    """Get available Kamiwaza AMIs for a region (up to limit)"""
    try:
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        import boto3
        from botocore.exceptions import ClientError

        # Get credentials
        provisioner = AWSCDKProvisioner()
        auth_method = settings.aws_auth_method

        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = settings.aws_assume_role_arn
                external_id = settings.aws_external_id
                session_name = settings.aws_session_name

                if not role_arn:
                    return []

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=region
                )
            elif auth_method == "access_keys":
                access_key = settings.aws_access_key_id
                secret_key = settings.aws_secret_access_key

                if not access_key or not secret_key:
                    return []

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': region
                }
        except Exception:
            return []

        # List AMIs
        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Get all AMIs owned by self and filter for Kamiwaza AMIs
        response = ec2_client.describe_images(
            Filters=[
                {
                    'Name': 'state',
                    'Values': ['available']
                }
            ],
            Owners=['self']
        )

        # Filter for Kamiwaza AMIs (check for either tag scheme)
        amis = []
        for image in response.get('Images', []):
            tags = {tag['Key']: tag['Value'] for tag in image.get('Tags', [])}
            # Check if it's a Kamiwaza AMI (either manually created or auto-created)
            if tags.get('Application') == 'Kamiwaza' or tags.get('ManagedBy') == 'KamiwazaDeploymentManager':
                amis.append({
                    'ami_id': image['ImageId'],
                    'name': image.get('Name', 'Unknown'),
                    'version': tags.get('Version', tags.get('KamiwazaVersion', 'Unknown')),
                    'creation_date': image.get('CreationDate', ''),
                    'state': image.get('State', 'unknown')
                })

        if not amis:
            return []

        # Sort by creation date (newest first)
        amis.sort(key=lambda x: x.get('creation_date', ''), reverse=True)

        # Return up to limit AMIs
        return amis[:limit]

    except Exception as e:
        logger.warning(f"Failed to get AMIs for region {region}: {str(e)}")
        return []


@app.get("/jobs/new", response_class=HTMLResponse)
async def new_job_form(
    request: Request
):
    """Display form to create new job"""
    csrf_token = csrf_protection.generate_token()

    # Try to get available AMIs for default region (up to 10)
    default_region = settings.allowed_regions_list[0] if settings.allowed_regions_list else "us-east-1"
    available_amis = get_available_amis(default_region, limit=10)

    return templates.TemplateResponse("job_new.html", {
        "request": request,
        "csrf_token": csrf_token,
        "allowed_regions": settings.allowed_regions_list,
        "allowed_instance_types": settings.allowed_instance_types_list,
        "allow_access_key_auth": settings.allow_access_key_auth,
        "available_amis": available_amis,
        "toolshed_stage": settings.toolshed_stage
    })


@app.post("/jobs")
async def create_job(
    request: Request,
    csrf_token: str = Form(...),
    job_name: str = Form(...),
    deployment_type: str = Form("docker"),
    kamiwaza_mode: Optional[str] = Form("full"),
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
    use_cached_ami: Optional[bool] = Form(False),
    tags: Optional[str] = Form(None),
    dockerhub_images: Optional[str] = Form(None),
    selected_apps: Optional[str] = Form("[]"),
    selected_tools: Optional[str] = Form("[]"),
    custom_mcp_github_urls: Optional[str] = Form("[]"),
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

        # Parse selected apps
        selected_apps_list = []
        if selected_apps:
            try:
                selected_apps_list = json.loads(selected_apps)
            except Exception as e:
                logger.warning(f"Failed to parse selected_apps: {str(e)}")

        # Parse selected tools
        selected_tools_list = []
        if selected_tools:
            try:
                selected_tools_list = json.loads(selected_tools)
            except Exception as e:
                logger.warning(f"Failed to parse selected_tools: {str(e)}")

        # Parse custom MCP GitHub URLs
        custom_mcp_urls_list = []
        if custom_mcp_github_urls:
            try:
                custom_mcp_urls_list = json.loads(custom_mcp_github_urls)
            except Exception as e:
                logger.warning(f"Failed to parse custom_mcp_github_urls: {str(e)}")

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
            kamiwaza_deployment_mode=kamiwaza_mode if deployment_type == "kamiwaza" else None,
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
            use_cached_ami=use_cached_ami if deployment_type == "kamiwaza" else False,
            tags=job_data.tags,
            dockerhub_images=[c.model_dump() for c in job_data.dockerhub_images] if job_data.dockerhub_images else [],
            selected_apps=selected_apps_list,
            selected_tools=selected_tools_list,
            custom_mcp_github_urls=custom_mcp_urls_list,
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


@app.post("/api/jobs/delete")
async def delete_jobs(
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete multiple jobs"""
    try:
        body = await request.json()
        job_ids = body.get("job_ids", [])
        csrf_token = body.get("csrf_token")

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        if not job_ids or not isinstance(job_ids, list):
            return JSONResponse({
                "success": False,
                "error": "No job IDs provided"
            }, status_code=400)

        # Convert job_ids to integers
        try:
            job_ids = [int(jid) for jid in job_ids]
        except (ValueError, TypeError):
            return JSONResponse({
                "success": False,
                "error": "Invalid job ID format"
            }, status_code=400)

        # Delete jobs and their related data
        deleted_count = 0
        for job_id in job_ids:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                # Delete related logs
                db.query(JobLog).filter(JobLog.job_id == job_id).delete()

                # Delete related files
                job_files = db.query(JobFile).filter(JobFile.job_id == job_id).all()
                for job_file in job_files:
                    # Delete physical file if it exists
                    try:
                        if job_file.file_path and Path(job_file.file_path).exists():
                            Path(job_file.file_path).unlink()
                    except Exception as e:
                        logger.warning(f"Could not delete file {job_file.file_path}: {str(e)}")
                    db.delete(job_file)

                # Delete the job itself
                db.delete(job)
                deleted_count += 1

        db.commit()

        logger.info(f"Deleted {deleted_count} job(s): {job_ids}")

        return JSONResponse({
            "success": True,
            "deleted_count": deleted_count
        })

    except Exception as e:
        logger.error(f"Error deleting jobs: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ============================================================================
# DEPLOYMENT MANAGER ROUTES (Kamiwaza User Provisioning)
# ============================================================================

@app.get("/deployment-manager", response_class=HTMLResponse)
async def deployment_manager_home(
    request: Request,
    db: Session = Depends(get_db)
):
    """Display Deployment Manager CSV upload form"""
    csrf_token = csrf_protection.generate_token()

    # Get available Kamiwaza instances (successful deployments that are ready)
    available_instances = db.query(Job).filter(
        Job.deployment_type == "kamiwaza",
        Job.status == "success",
        Job.kamiwaza_ready == True,
        Job.public_ip != None
    ).order_by(Job.completed_at.desc()).limit(10).all()

    # Format instances for dropdown
    instances = []
    for job in available_instances:
        instances.append({
            "id": job.id,
            "name": job.job_name,
            "url": f"https://{job.public_ip}",
            "public_ip": job.public_ip,
            "completed_at": job.completed_at.strftime('%Y-%m-%d %H:%M') if job.completed_at else "N/A"
        })

    # Use settings URL as fallback
    default_url = settings.kamiwaza_url

    return templates.TemplateResponse("deployment_manager.html", {
        "request": request,
        "csrf_token": csrf_token,
        "kamiwaza_url": default_url,
        "available_instances": instances
    })


# ============================================================================
# TOOLS + APPS MANAGEMENT ROUTES
# ============================================================================

@app.get("/tools-and-apps", response_class=HTMLResponse)
async def tools_and_apps_manager(
    request: Request,
    db: Session = Depends(get_db)
):
    """Display Tools + Apps management interface"""
    csrf_token = csrf_protection.generate_token()

    # Get available Kamiwaza instances (successful deployments that are ready)
    available_instances = db.query(Job).filter(
        Job.deployment_type == "kamiwaza",
        Job.status == "success",
        Job.kamiwaza_ready == True,
        Job.public_ip != None
    ).order_by(Job.completed_at.desc()).limit(10).all()

    # Format instances for dropdown
    instances = []
    for job in available_instances:
        instances.append({
            "id": job.id,
            "name": job.job_name,
            "url": f"https://{job.public_ip}",
            "public_ip": job.public_ip,
            "completed_at": job.completed_at.strftime('%Y-%m-%d %H:%M') if job.completed_at else "N/A"
        })

    # Use settings URL as fallback
    default_url = settings.kamiwaza_url

    return templates.TemplateResponse("tools_and_apps.html", {
        "request": request,
        "csrf_token": csrf_token,
        "kamiwaza_url": default_url,
        "available_instances": instances,
        "toolshed_stage": settings.toolshed_stage
    })


@app.post("/deployment-manager/provision")
async def create_provisioning_job(
    request: Request,
    csrf_token: str = Form(...),
    csv_file: UploadFile = File(...),
    target_kamiwaza_url: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Create a new Kamiwaza provisioning job"""

    # Verify CSRF token
    if not csrf_protection.verify_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Use selected URL or fall back to settings
    kamiwaza_url = target_kamiwaza_url if target_kamiwaza_url else settings.kamiwaza_url

    if not kamiwaza_url:
        raise HTTPException(status_code=400, detail="No target Kamiwaza URL specified")

    # User provisioning is done to an already-deployed Kamiwaza instance
    # The deployment mode is determined by that instance (must be "full" for user provisioning to work)
    deployment_mode = "full"

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
            deployment_type="docker",  # User provisioning uses docker deployment
            kamiwaza_deployment_mode=deployment_mode,  # Always "full" for user provisioning
            kamiwaza_repo=kamiwaza_url,  # Store target Kamiwaza URL
            aws_region="N/A",  # Not used for Kamiwaza provisioning
            aws_auth_method="N/A",
            instance_type="N/A",
            volume_size_gb=0,
            dockerhub_images=[],  # No custom images for user provisioning
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
        db.commit()  # Commit to get job_file.id
        db.refresh(job_file)

        # Now set the csv_file_id on the job
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
        "csrf_token": csrf_token,
        "kamiwaza_url": settings.kamiwaza_url
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

    # Read current configuration from os.environ to get latest values
    # This ensures we always show the most recently saved configuration
    config = {
        "KAMIWAZA_URL": os.environ.get("KAMIWAZA_URL", settings.kamiwaza_url),
        "KAMIWAZA_USERNAME": os.environ.get("KAMIWAZA_USERNAME", settings.kamiwaza_username),
        "KAMIWAZA_PASSWORD": os.environ.get("KAMIWAZA_PASSWORD", settings.kamiwaza_password),
        "KAMIWAZA_DB_PATH": os.environ.get("KAMIWAZA_DB_PATH", settings.kamiwaza_db_path),
        "KAMIWAZA_PACKAGE_URL": os.environ.get("KAMIWAZA_PACKAGE_URL", settings.kamiwaza_package_url),
        "APP_GARDEN_URL": os.environ.get("APP_GARDEN_URL", settings.app_garden_url),
        "KAMIWAZA_PROVISION_SCRIPT": os.environ.get("KAMIWAZA_PROVISION_SCRIPT", settings.kamiwaza_provision_script),
        "KAIZEN_SOURCE": os.environ.get("KAIZEN_SOURCE", settings.kaizen_source),
        "DEFAULT_USER_PASSWORD": os.environ.get("DEFAULT_USER_PASSWORD", settings.default_user_password),
        "AWS_AUTH_METHOD": os.environ.get("AWS_AUTH_METHOD", settings.aws_auth_method),
        "AWS_ASSUME_ROLE_ARN": os.environ.get("AWS_ASSUME_ROLE_ARN", settings.aws_assume_role_arn),
        "AWS_EXTERNAL_ID": os.environ.get("AWS_EXTERNAL_ID", settings.aws_external_id),
        "AWS_SESSION_NAME": os.environ.get("AWS_SESSION_NAME", settings.aws_session_name),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", settings.aws_access_key_id),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", settings.aws_secret_access_key),
        "AWS_SSO_PROFILE": os.environ.get("AWS_SSO_PROFILE", settings.aws_sso_profile),
        "AWS_PROVISIONING_METHOD": os.environ.get("AWS_PROVISIONING_METHOD", settings.aws_provisioning_method),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", settings.anthropic_api_key),
        "N2YO_API_KEY": os.environ.get("N2YO_API_KEY", settings.n2yo_api_key),
        "DATALASTIC_API_KEY": os.environ.get("DATALASTIC_API_KEY", settings.datalastic_api_key),
        "FLIGHTRADAR24_API_KEY": os.environ.get("FLIGHTRADAR24_API_KEY", settings.flightradar24_api_key),
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
    app_garden_url: str = Form("https://dev-info.kamiwaza.ai/garden/v2/apps.json"),
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

# Kamiwaza Package (RPM for RHEL 9)
KAMIWAZA_PACKAGE_URL={kamiwaza_package_url}

# App Garden & Toolshed
APP_GARDEN_URL={app_garden_url}

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
        os.environ["APP_GARDEN_URL"] = app_garden_url
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
            "APP_GARDEN_URL": app_garden_url,
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


@app.get("/api/cached-ami")
async def get_cached_ami_api(region: str = "us-east-1"):
    """Get available Kamiwaza AMIs for a specific region"""
    try:
        available_amis = get_available_amis(region, limit=10)
        if available_amis:
            return JSONResponse({
                "success": True,
                "amis": available_amis,
                "count": len(available_amis)
            })
        else:
            return JSONResponse({
                "success": False,
                "error": "No cached AMIs found for this region",
                "amis": [],
                "count": 0
            })
    except Exception as e:
        logger.error(f"Error fetching cached AMIs: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e),
            "amis": [],
            "count": 0
        }, status_code=500)


@app.get("/api/available-apps")
async def get_available_apps_for_creation():
    """Get available apps from app garden for job creation"""
    try:
        from app.kamiwaza_app_hydrator import KamiwazaAppHydrator

        # Fetch apps from app garden
        hydrator = KamiwazaAppHydrator()
        success, apps_data, error_msg = hydrator.fetch_app_garden_data()

        if not success:
            return JSONResponse({
                "success": False,
                "error": error_msg
            }, status_code=500)

        # Return apps with relevant info
        apps = []
        for app in apps_data:
            apps.append({
                "name": app.get("name", "Unknown"),
                "version": app.get("version", "Unknown"),
                "description": app.get("description", ""),
                "category": app.get("category", "app"),
                "tags": app.get("tags", []),
                "preview_image": app.get("preview_image", ""),
                "verified": app.get("verified", False),
                "risk_tier": app.get("risk_tier", 0)
            })

        return JSONResponse({
            "success": True,
            "apps": apps,
            "count": len(apps)
        })

    except Exception as e:
        logger.error(f"Error fetching available apps: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.get("/api/jobs/{job_id}/available-apps")
async def get_available_apps(job_id: int, db: Session = Depends(get_db)):
    """Get available apps from app garden for a job"""
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return JSONResponse({
                "success": False,
                "error": "Job not found"
            }, status_code=404)

        # Check if job is a Kamiwaza deployment
        if job.deployment_type != "kamiwaza":
            return JSONResponse({
                "success": False,
                "error": "This job is not a Kamiwaza deployment"
            }, status_code=400)

        from app.kamiwaza_app_hydrator import KamiwazaAppHydrator

        # Fetch apps from app garden
        hydrator = KamiwazaAppHydrator()
        success, apps_data, error_msg = hydrator.fetch_app_garden_data()

        if not success:
            return JSONResponse({
                "success": False,
                "error": error_msg
            }, status_code=500)

        # Return apps with relevant info
        apps = []
        for app in apps_data:
            apps.append({
                "name": app.get("name", "Unknown"),
                "version": app.get("version", "Unknown"),
                "description": app.get("description", ""),
                "category": app.get("category", "app"),
                "tags": app.get("tags", []),
                "preview_image": app.get("preview_image", ""),
                "verified": app.get("verified", False),
                "risk_tier": app.get("risk_tier", 0)
            })

        return JSONResponse({
            "success": True,
            "apps": apps,
            "count": len(apps)
        })

    except Exception as e:
        logger.error(f"Error fetching available apps: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/jobs/{job_id}/deploy-apps")
async def deploy_apps_to_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Deploy selected apps to a Kamiwaza instance"""
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")
        app_names = body.get("app_names", [])

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return JSONResponse({
                "success": False,
                "error": "Job not found"
            }, status_code=404)

        # Check if job is ready
        if not job.kamiwaza_ready:
            return JSONResponse({
                "success": False,
                "error": "Kamiwaza instance is not ready yet"
            }, status_code=400)

        if not app_names:
            return JSONResponse({
                "success": False,
                "error": "No apps selected"
            }, status_code=400)

        from app.kamiwaza_app_hydrator import KamiwazaAppHydrator

        # Fetch all available apps
        hydrator = KamiwazaAppHydrator()
        success, apps_data, error_msg = hydrator.fetch_app_garden_data()

        if not success:
            return JSONResponse({
                "success": False,
                "error": f"Failed to fetch app garden data: {error_msg}"
            }, status_code=500)

        # Filter selected apps
        selected_apps = [app for app in apps_data if app.get("name") in app_names]

        if not selected_apps:
            return JSONResponse({
                "success": False,
                "error": "No matching apps found"
            }, status_code=400)

        # Authenticate with Kamiwaza
        auth_success, token, auth_error = hydrator.authenticate()
        if not auth_success:
            return JSONResponse({
                "success": False,
                "error": f"Authentication failed: {auth_error}"
            }, status_code=500)

        # Deploy each app
        deployed_apps = []
        failed_apps = []

        for app in selected_apps:
            app_name = app.get("name", "Unknown")
            upload_success, upload_msg = hydrator.upload_app_template(token, app)

            if upload_success:
                deployed_apps.append(app_name)
                # Log deployment
                log = JobLog(
                    job_id=job.id,
                    level="info",
                    message=f"✓ Deployed app: {app_name} v{app.get('version', 'Unknown')}",
                    source="app-deployment"
                )
                db.add(log)
            else:
                failed_apps.append({"name": app_name, "error": upload_msg})
                # Log failure
                log = JobLog(
                    job_id=job.id,
                    level="error",
                    message=f"✗ Failed to deploy app {app_name}: {upload_msg}",
                    source="app-deployment"
                )
                db.add(log)

        db.commit()

        return JSONResponse({
            "success": True,
            "deployed": deployed_apps,
            "failed": failed_apps,
            "deployed_count": len(deployed_apps),
            "failed_count": len(failed_apps)
        })

    except Exception as e:
        logger.error(f"Error deploying apps: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


# ============================================================================
# TOOLSHED TOOLS ENDPOINTS
# ============================================================================

@app.get("/api/available-tools")
async def get_available_tools_for_creation():
    """Get available tools from toolshed for job creation"""
    try:
        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner

        # Create provisioner with default Kamiwaza URL
        provisioner = KamiwazaToolsProvisioner(
            kamiwaza_url=settings.kamiwaza_url,
            username=settings.kamiwaza_username,
            password=settings.kamiwaza_password,
            toolshed_stage=settings.toolshed_stage
        )

        # Authenticate
        success, token, error_msg = provisioner.authenticate()
        if not success:
            return JSONResponse({
                "success": False,
                "error": f"Authentication failed: {error_msg}"
            }, status_code=500)

        # Sync toolshed first
        sync_success, sync_msg = provisioner.sync_toolshed(token)
        if not sync_success:
            logger.warning(f"Toolshed sync failed: {sync_msg}, using cached templates")

        # Get available tool templates
        success, tools_data, error_msg = provisioner.get_available_tool_templates(token)

        if not success:
            return JSONResponse({
                "success": False,
                "error": error_msg
            }, status_code=500)

        # Return tools with relevant info
        tools = []
        for tool in tools_data:
            tools.append({
                "name": tool.get("name", "Unknown"),
                "description": tool.get("description", ""),
                "version": tool.get("version", "Unknown"),
                "category": tool.get("category", "tool"),
                "requires_config": tool.get("requires_config", False),
                "env_vars": tool.get("env_vars", [])
            })

        return JSONResponse({
            "success": True,
            "tools": tools,
            "count": len(tools)
        })

    except Exception as e:
        logger.error(f"Error fetching available tools: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.get("/api/jobs/{job_id}/available-tools")
async def get_available_tools(job_id: int, db: Session = Depends(get_db)):
    """Get available tools from toolshed for a job"""
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return JSONResponse({
                "success": False,
                "error": "Job not found"
            }, status_code=404)

        # Check if job is a Kamiwaza deployment
        if job.deployment_type != "kamiwaza":
            return JSONResponse({
                "success": False,
                "error": "This job is not a Kamiwaza deployment"
            }, status_code=400)

        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner

        # Check if Kamiwaza instance is ready
        if not job.kamiwaza_ready:
            return JSONResponse({
                "success": False,
                "error": "Kamiwaza instance is not ready yet. Please wait for deployment to complete."
            }, status_code=400)

        if not job.public_ip:
            return JSONResponse({
                "success": False,
                "error": "Kamiwaza instance has no public IP address"
            }, status_code=400)

        # Create provisioner pointing to the job's Kamiwaza instance
        kamiwaza_url = f"https://{job.public_ip}"
        provisioner = KamiwazaToolsProvisioner(
            kamiwaza_url=kamiwaza_url,
            username=settings.kamiwaza_username,
            password=settings.kamiwaza_password,
            toolshed_stage=settings.toolshed_stage
        )

        # Authenticate
        success, token, error_msg = provisioner.authenticate()
        if not success:
            # Return friendly error with suggestions
            friendly_msg = f"Cannot connect to Kamiwaza instance: {error_msg}\n\n"

            if "502" in error_msg or "Bad Gateway" in error_msg:
                friendly_msg += "This means the Kamiwaza backend service is not responding. Possible causes:\n"
                friendly_msg += "• Backend container is not running\n"
                friendly_msg += "• Keycloak authentication service is down\n"
                friendly_msg += "• Instance is still starting up (can take 20-30 minutes)\n\n"
                friendly_msg += "Check the job deployment logs or SSH into the instance to diagnose."
            elif "Connection" in error_msg or "Timeout" in error_msg:
                friendly_msg += "The instance is not reachable. Check if it's running and accessible."

            return JSONResponse({
                "success": False,
                "error": friendly_msg.strip()
            }, status_code=500)

        # Sync toolshed first (important!)
        sync_success, sync_msg = provisioner.sync_toolshed(token)
        if not sync_success:
            logger.warning(f"Toolshed sync failed for job {job_id}: {sync_msg}, will try to use cached templates")

        # Get available tool templates
        success, tools_data, error_msg = provisioner.get_available_tool_templates(token)

        if not success:
            return JSONResponse({
                "success": False,
                "error": error_msg
            }, status_code=500)

        # Return tools with relevant info
        tools = []
        for tool in tools_data:
            tools.append({
                "name": tool.get("name", "Unknown"),
                "description": tool.get("description", ""),
                "version": tool.get("version", "Unknown"),
                "category": tool.get("category", "tool"),
                "requires_config": tool.get("requires_config", False),
                "env_vars": tool.get("env_vars", [])
            })

        return JSONResponse({
            "success": True,
            "tools": tools,
            "count": len(tools)
        })

    except Exception as e:
        logger.error(f"Error fetching available tools: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/jobs/{job_id}/deploy-tools")
async def deploy_tools_to_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Deploy selected tools to a Kamiwaza instance"""
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")
        tool_names = body.get("tool_names", [])

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return JSONResponse({
                "success": False,
                "error": "Job not found"
            }, status_code=404)

        # Check if job is ready
        if not job.kamiwaza_ready:
            return JSONResponse({
                "success": False,
                "error": "Kamiwaza instance is not ready yet"
            }, status_code=400)

        if not tool_names:
            return JSONResponse({
                "success": False,
                "error": "No tools selected"
            }, status_code=400)

        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner

        # Create provisioner pointing to the job's Kamiwaza instance
        kamiwaza_url = f"https://{job.public_ip}" if job.public_ip else settings.kamiwaza_url
        provisioner = KamiwazaToolsProvisioner(
            kamiwaza_url=kamiwaza_url,
            username=settings.kamiwaza_username,
            password=settings.kamiwaza_password,
            toolshed_stage=settings.toolshed_stage
        )

        # Authenticate
        auth_success, token, auth_error = provisioner.authenticate()
        if not auth_success:
            return JSONResponse({
                "success": False,
                "error": f"Authentication failed: {auth_error}"
            }, status_code=500)

        # Deploy each tool
        deployed_tools = []
        failed_tools = []

        for tool_name in tool_names:
            deploy_success, deploy_msg = provisioner.deploy_tool(token, tool_name)

            if deploy_success:
                deployed_tools.append(tool_name)
                # Log deployment
                log = JobLog(
                    job_id=job.id,
                    level="info",
                    message=f"✓ Deployed tool: {tool_name}",
                    source="tool-deployment"
                )
                db.add(log)
            else:
                failed_tools.append({"name": tool_name, "error": deploy_msg})
                # Log failure
                log = JobLog(
                    job_id=job.id,
                    level="error",
                    message=f"✗ Failed to deploy tool {tool_name}: {deploy_msg}",
                    source="tool-deployment"
                )
                db.add(log)

        # Update job's tool deployment status
        if not job.tool_deployment_status:
            job.tool_deployment_status = {}

        for tool_name in deployed_tools:
            job.tool_deployment_status[tool_name] = "success"

        for failed_tool in failed_tools:
            job.tool_deployment_status[failed_tool["name"]] = "failed"

        db.commit()

        return JSONResponse({
            "success": True,
            "deployed": deployed_tools,
            "failed": failed_tools,
            "deployed_count": len(deployed_tools),
            "failed_count": len(failed_tools)
        })

    except Exception as e:
        logger.error(f"Error deploying tools: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


# ============================================================================
# MCP GITHUB IMPORT ENDPOINTS
# ============================================================================

@app.post("/api/mcp/validate-github")
async def validate_mcp_github_url(request: Request):
    """
    Validate an MCP tool from a GitHub URL.
    Performs basic validation of repository structure.
    """
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")
        github_url = body.get("github_url")
        github_token = body.get("github_token")  # Optional

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        if not github_url:
            return JSONResponse({
                "success": False,
                "error": "github_url is required"
            }, status_code=400)

        from app.mcp_github_importer import MCPGitHubImporter

        # Create importer
        importer = MCPGitHubImporter(github_token=github_token)

        # Validate repository
        success, tool_config, log_lines = importer.validate_mcp_repo(github_url)

        if success:
            return JSONResponse({
                "success": True,
                "tool_config": tool_config,
                "validation_logs": log_lines
            })
        else:
            return JSONResponse({
                "success": False,
                "error": "Validation failed",
                "validation_logs": log_lines
            }, status_code=400)

    except Exception as e:
        logger.error(f"Error validating MCP GitHub URL: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/mcp/import-to-kamiwaza")
async def import_mcp_to_kamiwaza(request: Request, db: Session = Depends(get_db)):
    """
    Import an MCP tool from GitHub to a Kamiwaza instance.
    Validates the tool first, then registers it to Kamiwaza's toolshed.
    """
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")
        github_url = body.get("github_url")
        github_token = body.get("github_token")  # Optional
        job_id = body.get("job_id")  # Optional: if importing for a specific job

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        if not github_url:
            return JSONResponse({
                "success": False,
                "error": "github_url is required"
            }, status_code=400)

        from app.mcp_github_importer import MCPGitHubImporter

        # Create importer
        importer = MCPGitHubImporter(github_token=github_token)

        # Step 1: Validate repository
        success, tool_config, validation_logs = importer.validate_mcp_repo(github_url)
        if not success:
            return JSONResponse({
                "success": False,
                "error": "Tool validation failed",
                "validation_logs": validation_logs
            }, status_code=400)

        # Step 2: Determine Kamiwaza URL
        kamiwaza_url = settings.kamiwaza_url
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.public_ip:
                kamiwaza_url = f"https://{job.public_ip}"

        # Step 3: Authenticate with Kamiwaza
        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner
        provisioner = KamiwazaToolsProvisioner(
            kamiwaza_url=kamiwaza_url,
            username=settings.kamiwaza_username,
            password=settings.kamiwaza_password
        )

        auth_success, token, auth_error = provisioner.authenticate()
        if not auth_success:
            return JSONResponse({
                "success": False,
                "error": f"Authentication failed: {auth_error}"
            }, status_code=500)

        # Step 4: Import to Kamiwaza
        import_success, import_message = importer.import_to_kamiwaza(
            kamiwaza_url,
            token,
            tool_config,
            github_url
        )

        if import_success:
            # Log import if for a specific job
            if job_id:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    log = JobLog(
                        job_id=job.id,
                        level="info",
                        message=f"✓ Imported MCP tool from GitHub: {tool_config['name']}",
                        source="mcp-import"
                    )
                    db.add(log)
                    db.commit()

            return JSONResponse({
                "success": True,
                "message": import_message,
                "tool_name": tool_config['name'],
                "validation_logs": validation_logs
            })
        else:
            return JSONResponse({
                "success": False,
                "error": import_message,
                "validation_logs": validation_logs
            }, status_code=500)

    except Exception as e:
        logger.error(f"Error importing MCP to Kamiwaza: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


# ============================================================================
# MCP GITHUB IMPORT ENDPOINTS
# ============================================================================

@app.post("/api/mcp/validate-github")
async def validate_mcp_github(request: Request):
    """Validate an MCP tool from GitHub URL"""
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")
        github_url = body.get("github_url")

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        if not github_url:
            return JSONResponse({
                "success": False,
                "error": "github_url is required"
            }, status_code=400)

        from app.mcp_github_importer import MCPGitHubImporter

        # Create importer and validate
        importer = MCPGitHubImporter()
        success, tool_config, validation_logs = importer.validate_mcp_repo(github_url)

        if success:
            return JSONResponse({
                "success": True,
                "tool_config": tool_config,
                "validation_logs": validation_logs
            })
        else:
            return JSONResponse({
                "success": False,
                "error": "MCP tool validation failed. Check validation logs for details.",
                "validation_logs": validation_logs
            }, status_code=400)

    except Exception as e:
        logger.error(f"Error validating MCP GitHub URL: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/app-garden/publish")
async def publish_app_to_garden(request: Request):
    """
    Publish a new app or update an existing app in the App Garden.
    This allows deployment manager to push apps to the App Garden registry.
    """
    try:
        import httpx

        body = await request.json()
        csrf_token = body.get("csrf_token")

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        # Extract app data
        app_data = body.get("app_data")
        if not app_data:
            return JSONResponse({
                "success": False,
                "error": "app_data is required"
            }, status_code=400)

        # Validate required fields
        required_fields = ["name", "version", "docker_images", "compose_yml"]
        missing_fields = [field for field in required_fields if field not in app_data]
        if missing_fields:
            return JSONResponse({
                "success": False,
                "error": f"Missing required fields: {', '.join(missing_fields)}"
            }, status_code=400)

        # Get App Garden API URL from settings
        from app.config import settings
        app_garden_api_url = settings.app_garden_api_url
        if not app_garden_api_url:
            return JSONResponse({
                "success": False,
                "error": "APP_GARDEN_API_URL not configured. Cannot publish to App Garden. Please configure in Settings."
            }, status_code=500)

        # Get API key for App Garden (if required)
        app_garden_api_key = settings.app_garden_api_key

        # Publish to App Garden
        headers = {"Content-Type": "application/json"}
        if app_garden_api_key:
            headers["Authorization"] = f"Bearer {app_garden_api_key}"

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{app_garden_api_url}/apps",
                json=app_data,
                headers=headers
            )

            if response.status_code in [200, 201]:
                return JSONResponse({
                    "success": True,
                    "message": f"Successfully published app '{app_data['name']}' to App Garden",
                    "data": response.json()
                })
            else:
                return JSONResponse({
                    "success": False,
                    "error": f"App Garden API error: HTTP {response.status_code}",
                    "details": response.text
                }, status_code=response.status_code)

    except Exception as e:
        logger.error(f"Error publishing to App Garden: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


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


@app.get("/ami-manager", response_class=HTMLResponse)
async def ami_manager_page(
    request: Request
):
    """Display AMI management page"""
    csrf_token = csrf_protection.generate_token()

    # Check if base AWS credentials are available
    from app.aws_cdk_provisioner import AWSCDKProvisioner
    provisioner = AWSCDKProvisioner()
    credentials_available, credentials_message = provisioner.check_base_credentials()

    # Get default package URL from settings
    default_package_url = os.environ.get(
        "KAMIWAZA_PACKAGE_URL",
        "https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/rpm/rhel9/x86_64/kamiwaza_v0.9.2_rhel9_x86_64-online_rc18.rpm"
    )

    return templates.TemplateResponse("ami_manager.html", {
        "request": request,
        "csrf_token": csrf_token,
        "aws_credentials_available": credentials_available,
        "aws_credentials_message": credentials_message,
        "allowed_regions": settings.allowed_regions_list,
        "allowed_instance_types": settings.allowed_instance_types_list,
        "default_package_url": default_package_url
    })


@app.get("/api/amis")
async def list_amis(
    region: Optional[str] = None
):
    """List all Kamiwaza AMIs"""
    try:
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        import boto3
        from botocore.exceptions import ClientError

        # Get credentials
        provisioner = AWSCDKProvisioner()
        auth_method = settings.aws_auth_method

        if not region:
            region = "us-east-1"  # Default region

        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = settings.aws_assume_role_arn
                external_id = settings.aws_external_id
                session_name = settings.aws_session_name

                if not role_arn:
                    raise Exception("AWS_ASSUME_ROLE_ARN not configured")

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=region
                )
            elif auth_method == "access_keys":
                access_key = settings.aws_access_key_id
                secret_key = settings.aws_secret_access_key

                if not access_key or not secret_key:
                    raise Exception("AWS credentials not configured")

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': region
                }
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": f"Failed to get AWS credentials: {str(e)}"
            }, status_code=500)

        # List AMIs
        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Get all AMIs owned by self
        response = ec2_client.describe_images(
            Owners=['self']
        )

        amis = []
        for image in response.get('Images', []):
            # Extract tags
            tags = {tag['Key']: tag['Value'] for tag in image.get('Tags', [])}

            # Only include Kamiwaza AMIs (either manually created or auto-created)
            if not (tags.get('Application') == 'Kamiwaza' or tags.get('ManagedBy') == 'KamiwazaDeploymentManager'):
                continue

            # Get snapshot info
            snapshots = []
            total_size = 0
            for bdm in image.get('BlockDeviceMappings', []):
                if 'Ebs' in bdm:
                    snap_id = bdm['Ebs'].get('SnapshotId')
                    size = bdm['Ebs'].get('VolumeSize', 0)
                    if snap_id:
                        snapshots.append(snap_id)
                        total_size += size

            amis.append({
                'ami_id': image['ImageId'],
                'name': image.get('Name', 'Unknown'),
                'description': image.get('Description', ''),
                'state': image.get('State', 'unknown'),
                'creation_date': image.get('CreationDate', ''),
                'size_gb': total_size,
                'version': tags.get('Version', tags.get('KamiwazaVersion', 'Unknown')),
                'created_from': tags.get('CreatedFrom', ''),
                'created_from_job': tags.get('CreatedFromJob', ''),
                'auto_created': tags.get('AutoCreated', 'false'),
                'snapshots': snapshots,
                'snapshot_count': len(snapshots)
            })

        # Sort by creation date (newest first)
        amis.sort(key=lambda x: x['creation_date'], reverse=True)

        return JSONResponse({
            "success": True,
            "amis": amis,
            "region": region,
            "count": len(amis)
        })

    except ClientError as e:
        return JSONResponse({
            "success": False,
            "error": f"AWS error: {e.response['Error']['Message']}"
        }, status_code=500)
    except Exception as e:
        logger.error(f"Error listing AMIs: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/amis/update-status")
async def update_ami_status(
    db: Session = Depends(get_db)
):
    """Update AMI creation status for jobs with pending AMIs"""
    try:
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        import boto3
        from botocore.exceptions import ClientError

        # Get credentials
        provisioner = AWSCDKProvisioner()
        auth_method = settings.aws_auth_method
        region = "us-east-1"  # Default region

        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = settings.aws_assume_role_arn
                external_id = settings.aws_external_id
                session_name = settings.aws_session_name

                if not role_arn:
                    raise Exception("AWS_ASSUME_ROLE_ARN not configured")

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=region
                )
            elif auth_method == "access_keys":
                access_key = settings.aws_access_key_id
                secret_key = settings.aws_secret_access_key

                if not access_key or not secret_key:
                    raise Exception("AWS credentials not configured")

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': region
                }
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": f"Failed to get AWS credentials: {str(e)}"
            }, status_code=500)

        # Find jobs with pending AMI creation
        jobs_with_pending_amis = db.query(Job).filter(
            Job.ami_creation_status == "creating",
            Job.created_ami_id.isnot(None)
        ).all()

        if not jobs_with_pending_amis:
            return JSONResponse({
                "success": True,
                "message": "No jobs with pending AMIs",
                "updated": 0
            })

        # Create EC2 client
        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        updated_count = 0
        for job in jobs_with_pending_amis:
            try:
                # Check AMI status in AWS
                response = ec2_client.describe_images(ImageIds=[job.created_ami_id])

                if response['Images']:
                    ami = response['Images'][0]
                    ami_state = ami.get('State', 'unknown')

                    if ami_state == 'available':
                        # AMI is now available!
                        job.ami_creation_status = 'completed'
                        job.ami_created_at = datetime.utcnow()

                        # Add log
                        from app.models import JobLog
                        log = JobLog(
                            job_id=job.id,
                            level="info",
                            message=f"✓ AMI {job.created_ami_id} is now available!",
                            source="ami-status-update"
                        )
                        db.add(log)
                        updated_count += 1

                    elif ami_state == 'failed':
                        job.ami_creation_status = 'failed'
                        job.ami_creation_error = 'AMI creation failed in AWS'

                        from app.models import JobLog
                        log = JobLog(
                            job_id=job.id,
                            level="error",
                            message=f"✗ AMI {job.created_ami_id} creation failed",
                            source="ami-status-update"
                        )
                        db.add(log)
                        updated_count += 1

            except ClientError as e:
                logger.warning(f"Error checking AMI {job.created_ami_id} for job {job.id}: {e}")
                continue

        db.commit()

        return JSONResponse({
            "success": True,
            "message": f"Updated {updated_count} AMI statuses",
            "updated": updated_count,
            "checked": len(jobs_with_pending_amis)
        })

    except Exception as e:
        logger.error(f"Error updating AMI statuses: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/amis/{ami_id}/delete")
async def delete_ami(
    ami_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete an AMI and its associated snapshots"""
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")
        region = body.get("region", "us-east-1")

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        from app.aws_cdk_provisioner import AWSCDKProvisioner
        import boto3

        # Get credentials
        provisioner = AWSCDKProvisioner()
        auth_method = settings.aws_auth_method

        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = settings.aws_assume_role_arn
                external_id = settings.aws_external_id
                session_name = settings.aws_session_name

                if not role_arn:
                    raise Exception("AWS_ASSUME_ROLE_ARN not configured")

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=region
                )
            elif auth_method == "access_keys":
                access_key = settings.aws_access_key_id
                secret_key = settings.aws_secret_access_key

                if not access_key or not secret_key:
                    raise Exception("AWS credentials not configured")

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': region
                }
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": f"Failed to get AWS credentials: {str(e)}"
            }, status_code=500)

        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Get AMI details first
        ami_info = ec2_client.describe_images(ImageIds=[ami_id])
        if not ami_info['Images']:
            return JSONResponse({
                "success": False,
                "error": f"AMI {ami_id} not found"
            }, status_code=404)

        image = ami_info['Images'][0]
        ami_name = image.get('Name', 'Unknown')

        # Get snapshots
        snapshots = []
        for bdm in image.get('BlockDeviceMappings', []):
            if 'Ebs' in bdm and 'SnapshotId' in bdm['Ebs']:
                snapshots.append(bdm['Ebs']['SnapshotId'])

        # Deregister AMI
        logger.info(f"Deleting AMI {ami_id} ({ami_name})")
        ec2_client.deregister_image(ImageId=ami_id)

        # Delete snapshots
        deleted_snapshots = []
        for snap_id in snapshots:
            try:
                ec2_client.delete_snapshot(SnapshotId=snap_id)
                deleted_snapshots.append(snap_id)
                logger.info(f"Deleted snapshot {snap_id}")
            except Exception as e:
                logger.warning(f"Failed to delete snapshot {snap_id}: {str(e)}")

        return JSONResponse({
            "success": True,
            "message": f"AMI {ami_id} deleted successfully",
            "ami_id": ami_id,
            "ami_name": ami_name,
            "deleted_snapshots": len(deleted_snapshots),
            "snapshots": deleted_snapshots
        })

    except ClientError as e:
        error_msg = e.response['Error']['Message']
        logger.error(f"AWS error deleting AMI {ami_id}: {error_msg}")
        return JSONResponse({
            "success": False,
            "error": f"AWS error: {error_msg}"
        }, status_code=500)
    except Exception as e:
        logger.error(f"Error deleting AMI {ami_id}: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/amis/create")
async def create_ami_from_package(
    request: Request,
    db: Session = Depends(get_db)
):
    """Create an AMI from a Kamiwaza .deb package"""
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        # Extract parameters
        region = body.get("region")
        package_url = body.get("package_url")
        version = body.get("version")
        instance_type = body.get("instance_type", "t3.xlarge")
        deployment_mode = body.get("deployment_mode", "full")

        # Validate required fields
        if not all([region, package_url, version]):
            return JSONResponse({
                "success": False,
                "error": "Missing required fields: region, package_url, version"
            }, status_code=400)

        # Normalize version tag
        if not version.startswith('v'):
            version = f'v{version}'

        # Create a special job for AMI creation
        job_name = f"AMI Creation - {version}"

        # Get auth method and related fields from settings
        auth_method = settings.aws_auth_method

        # Create job in database
        job = Job(
            job_name=job_name,
            requester_email="system@kamiwaza.ai",  # System job
            deployment_type="kamiwaza",
            aws_region=region,
            aws_auth_method=auth_method,  # Required field
            assume_role_arn=settings.aws_assume_role_arn if auth_method == "assume_role" else None,
            external_id=settings.aws_external_id if auth_method == "assume_role" else None,
            session_name=settings.aws_session_name if auth_method == "assume_role" else None,
            instance_type=instance_type,
            volume_size_gb=100,  # Sufficient for Kamiwaza
            status="pending",
            kamiwaza_deployment_mode=deployment_mode,
            kamiwaza_branch=version,  # Store version in branch field
            use_cached_ami=False,  # Don't use cached AMI when building new AMI
            dockerhub_images=[],  # Required field (empty for Kamiwaza deployments)
            tags={
                "Purpose": "AMI-Creation",
                "Version": version,
                "CreatedFrom": "AMI-Manager",
                "PackageURL": package_url  # Store package URL in tags
            }
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        logger.info(f"Created AMI creation job {job.id} for version {version}")

        # Trigger the provisioning job (will auto-create AMI when ready)
        from worker.tasks import execute_provisioning_job
        execute_provisioning_job.apply_async(args=[job.id])

        # Log the creation
        from app.models import JobLog
        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"AMI creation job started for Kamiwaza {version}",
            source="ami-manager"
        )
        db.add(log)

        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"Package URL: {package_url}",
            source="ami-manager"
        )
        db.add(log)

        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"Deployment Mode: {deployment_mode}",
            source="ami-manager"
        )
        db.add(log)

        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"Expected completion time: ~40-50 minutes",
            source="ami-manager"
        )
        db.add(log)

        db.commit()

        return JSONResponse({
            "success": True,
            "job_id": job.id,
            "message": f"AMI creation job started for version {version}",
            "estimated_time_minutes": 50
        })

    except Exception as e:
        logger.error(f"Error creating AMI job: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/jobs/{job_id}/destroy-stack")
async def destroy_cloudformation_stack(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete the CloudFormation stack for a job"""
    try:
        body = await request.json()
        csrf_token = body.get("csrf_token")

        # Verify CSRF token
        if not csrf_protection.verify_token(csrf_token):
            return JSONResponse({
                "success": False,
                "error": "Invalid CSRF token"
            }, status_code=403)

        # Get job from database
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return JSONResponse({
                "success": False,
                "error": "Job not found"
            }, status_code=404)

        # Check if job has been deployed
        if not job.instance_id and job.status != "success":
            return JSONResponse({
                "success": False,
                "error": "No CloudFormation stack exists for this job"
            }, status_code=400)

        from app.aws_cdk_provisioner import AWSCDKProvisioner
        import boto3
        from botocore.exceptions import NoCredentialsError, ClientError as BotoClientError

        # Get credentials
        provisioner = AWSCDKProvisioner()
        auth_method = job.aws_auth_method or settings.aws_auth_method

        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = job.assume_role_arn or settings.aws_assume_role_arn
                external_id = job.external_id or settings.aws_external_id
                session_name = job.session_name or settings.aws_session_name

                if not role_arn:
                    raise Exception("AWS_ASSUME_ROLE_ARN not configured")

                # First check if base credentials are available
                try:
                    sts_test = boto3.client('sts')
                    caller_id = sts_test.get_caller_identity()
                    logger.info(f"Base credentials found: {caller_id.get('Arn')}")
                except NoCredentialsError:
                    raise Exception(
                        "No base AWS credentials found. To assume a role, you need base credentials configured. "
                        "Please set up AWS SSO (run 'aws sso login'), set environment variables "
                        "(AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY), or configure an IAM instance profile."
                    )
                except BotoClientError as e:
                    raise Exception(f"Base credentials are invalid: {str(e)}")

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=job.aws_region
                )
            elif auth_method == "access_keys":
                access_key = settings.aws_access_key_id
                secret_key = settings.aws_secret_access_key

                if not access_key or not secret_key:
                    raise Exception("AWS access keys not configured in settings")

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': job.aws_region
                }
            else:
                raise Exception(f"Unknown AWS auth method: {auth_method}")
        except Exception as e:
            logger.error(f"Failed to get AWS credentials for job {job_id}: {str(e)}")
            return JSONResponse({
                "success": False,
                "error": f"Failed to get AWS credentials: {str(e)}"
            }, status_code=500)

        # Log stack deletion start
        log = JobLog(
            job_id=job.id,
            level="info",
            message=f"Starting CloudFormation stack deletion for kamiwaza-job-{job_id}",
            source="system"
        )
        db.add(log)
        db.commit()

        # Call CDK destroy
        success, log_lines = provisioner.destroy_ec2_instance(
            job_id=job_id,
            credentials=credentials,
            callback=lambda msg: db.add(JobLog(
                job_id=job.id,
                level="info",
                message=msg,
                source="cdk"
            )) or db.commit()
        )

        if success:
            # Update job status
            job.status = "destroyed"
            job.instance_id = None
            job.public_ip = None
            job.private_ip = None

            # Log success
            log = JobLog(
                job_id=job.id,
                level="info",
                message=f"CloudFormation stack kamiwaza-job-{job_id} destroyed successfully",
                source="system"
            )
            db.add(log)
            db.commit()

            logger.info(f"Successfully destroyed CloudFormation stack for job {job_id}")

            return JSONResponse({
                "success": True,
                "message": f"CloudFormation stack destroyed successfully",
                "job_id": job_id
            })
        else:
            # Log failure
            error_msg = "\n".join(log_lines[-10:]) if log_lines else "Unknown error"
            log = JobLog(
                job_id=job.id,
                level="error",
                message=f"Failed to destroy CloudFormation stack: {error_msg}",
                source="system"
            )
            db.add(log)
            db.commit()

            logger.error(f"Failed to destroy CloudFormation stack for job {job_id}: {error_msg}")

            return JSONResponse({
                "success": False,
                "error": f"Failed to destroy stack: {error_msg}"
            }, status_code=500)

    except Exception as e:
        logger.error(f"Error destroying CloudFormation stack for job {job_id}: {str(e)}")

        # Log error
        try:
            log = JobLog(
                job_id=job_id,
                level="error",
                message=f"Error destroying stack: {str(e)}",
                source="system"
            )
            db.add(log)
            db.commit()
        except:
            pass

        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
