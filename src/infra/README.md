# Infrastructure

Planned one-VM deployment only after local gate and approval. No cloud provisioned.
Jiaxin prepares configuration, backup/restore and restart scripts; Chuying provides resource measurements; Zhihao reviews budget and deployment.

Include persistent DB volume, private database network, HTTPS, least privilege, bounded logs and encrypted off-VM backups. Exact VM and cost estimate remain deployment tasks. Do not add load balancers/queues/NAT gateways by default.
