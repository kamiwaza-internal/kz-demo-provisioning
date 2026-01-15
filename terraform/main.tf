terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Data source for latest Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Data source for default VPC (if not specified)
data "aws_vpc" "default" {
  count   = var.vpc_id == "" ? 1 : 0
  default = true
}

# Data source for default subnet (if not specified)
data "aws_subnets" "default" {
  count = var.vpc_id == "" && var.subnet_id == "" ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# Determine VPC ID
locals {
  vpc_id    = var.vpc_id != "" ? var.vpc_id : (length(data.aws_vpc.default) > 0 ? data.aws_vpc.default[0].id : "")
  subnet_id = var.subnet_id != "" ? var.subnet_id : (length(data.aws_subnets.default) > 0 && length(data.aws_subnets.default[0].ids) > 0 ? data.aws_subnets.default[0].ids[0] : "")
  ami_id    = var.ami_id != "" ? var.ami_id : data.aws_ami.amazon_linux_2023.id

  use_custom_sg = length(var.security_group_ids) > 0
  create_sg     = !local.use_custom_sg

  security_group_ids = local.use_custom_sg ? var.security_group_ids : [aws_security_group.instance[0].id]

  common_tags = merge(
    {
      Name        = var.job_name
      ManagedBy   = "Terraform"
      Application = "EC2-Provisioning"
    },
    var.tags
  )
}

# Security Group (created only if not provided)
resource "aws_security_group" "instance" {
  count       = local.create_sg ? 1 : 0
  name        = "${var.job_name}-sg"
  description = "Security group for ${var.job_name}"
  vpc_id      = local.vpc_id

  # Allow outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  # Allow HTTP
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTP"
  }

  # Allow HTTPS
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTPS"
  }

  # Allow SSH (restricted - adjust CIDR as needed)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # TODO: Restrict to specific CIDR
    description = "Allow SSH"
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${var.job_name}-sg"
    }
  )
}

# IAM Role for EC2 instance (for SSM and other AWS services)
resource "aws_iam_role" "instance" {
  name = "${var.job_name}-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

# Attach SSM managed policy for Systems Manager access
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Instance profile
resource "aws_iam_instance_profile" "instance" {
  name = "${var.job_name}-instance-profile"
  role = aws_iam_role.instance.name

  tags = local.common_tags
}

# EC2 Instance
resource "aws_instance" "main" {
  ami           = local.ami_id
  instance_type = var.instance_type
  subnet_id     = local.subnet_id

  vpc_security_group_ids = local.security_group_ids
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  key_name = var.key_pair_name != "" ? var.key_pair_name : null

  root_block_device {
    volume_size           = var.volume_size
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
  }

  user_data = var.user_data != "" ? var.user_data : null

  metadata_options {
    http_tokens                 = "required" # IMDSv2
    http_put_response_hop_limit = 1
  }

  tags = merge(
    local.common_tags,
    {
      Name = var.job_name
    }
  )

  lifecycle {
    ignore_changes = [ami]
  }
}
