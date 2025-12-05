variable "project_name" {
  default = "cs3-nca"
}

variable "vpc_cidr" {
  default = "10.0.0.0/16"
}

variable "my_ip_cidr" {
  description = "Your IP address for SSH access (e.g., '1.2.3.4/32')"
  type        = string
  default     = "192.168.1.125/32" # Change this to your IP!
}

variable "key_pair_name" {
  default = "case3-keypair"
}
