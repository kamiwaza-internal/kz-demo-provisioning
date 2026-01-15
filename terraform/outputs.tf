output "instance_id" {
  description = "ID of the EC2 instance"
  value       = aws_instance.main.id
}

output "public_ip" {
  description = "Public IP address of the instance"
  value       = aws_instance.main.public_ip
}

output "private_ip" {
  description = "Private IP address of the instance"
  value       = aws_instance.main.private_ip
}

output "instance_arn" {
  description = "ARN of the EC2 instance"
  value       = aws_instance.main.arn
}

output "security_group_id" {
  description = "ID of the security group (if created)"
  value       = local.create_sg ? aws_security_group.instance[0].id : null
}

output "iam_role_arn" {
  description = "ARN of the IAM role"
  value       = aws_iam_role.instance.arn
}

output "instance_profile_arn" {
  description = "ARN of the instance profile"
  value       = aws_iam_instance_profile.instance.arn
}
