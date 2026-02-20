variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
}

variable "job_name" {
  description = "Name of the provisioning job"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "volume_size" {
  description = "Root volume size in GB"
  type        = number
  default     = 30
}

variable "ami_id" {
  description = "AMI ID to use (optional, will use latest Amazon Linux 2023 if not provided)"
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "VPC ID (optional, will use default VPC if not provided)"
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Subnet ID (optional, will use default subnet if not provided)"
  type        = string
  default     = ""
}

variable "security_group_ids" {
  description = "List of security group IDs (optional, will create default if not provided)"
  type        = list(string)
  default     = []
}

variable "key_pair_name" {
  description = "EC2 key pair name (optional)"
  type        = string
  default     = ""
}

variable "user_data" {
  description = "User data script for instance initialization"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "ssh_allowed_cidrs" {
  description = "List of CIDR blocks allowed to SSH (port 22). Default empty = no public SSH; use SSM for access."
  type        = list(string)
  default     = []
}
