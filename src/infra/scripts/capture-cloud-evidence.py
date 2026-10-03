"""Read-only AWS evidence capture with redaction. Only describe/get/list calls."""
import json, re, subprocess, sys, datetime, pathlib

PROFILE, REGION = "inf2006-lab", "us-east-1"
OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
STACKS = {"base": "inf2006-private-base-retry1", "ingress": "inf2006-private-ingress", "app": "inf2006-private-app"}

_maps = {}
def _tok(kind, value):
    m = _maps.setdefault(kind, {})
    return m.setdefault(value, f"<{kind}-{len(m) + 1}>")

def redact(text):
    text = re.sub(r"arn:aws:[a-z0-9\-]+:[a-z0-9\-]*:\d{12}:[^\s\"',]+", lambda m: "<arn:" + m.group(0).split(":")[2] + ">", text)
    text = re.sub(r"\b\d{12}\b", "<account-id>", text)
    for kind, pat in [("instance", r"\bi-[0-9a-f]{8,17}\b"), ("sg", r"\bsg-[0-9a-f]{8,17}\b"),
                      ("subnet", r"\bsubnet-[0-9a-f]{8,17}\b"), ("vpc", r"\bvpc-[0-9a-f]{8,17}\b"),
                      ("vpce", r"\bvpce-[0-9a-f]{8,17}\b"), ("nat", r"\bnat-[0-9a-f]{8,17}\b"),
                      ("eni", r"\beni-[0-9a-f]{8,17}\b"), ("ami", r"\bami-[0-9a-f]{8,17}\b"),
                      ("lt", r"\blt-[0-9a-f]{8,17}\b")]:
        text = re.sub(pat, lambda m, k=kind: _tok(k, m.group(0)), text)
    text = re.sub(r"\b[a-z0-9]{10}\.execute-api\.[a-z0-9\-]+\.amazonaws\.com", "<api-id>.execute-api.<region>.amazonaws.com", text)
    text = re.sub(r"\b[a-z0-9\-]+\.duckdns\.org\b", "<certificate-hostname>", text)
    text = re.sub(r"internal-[A-Za-z0-9\-]+\.[a-z0-9\-]+\.elb\.amazonaws\.com", "<internal-alb-dns>", text)
    text = re.sub(r"[A-Za-z0-9\-]+\.[a-z0-9]+\.[a-z0-9\-]+\.rds\.amazonaws\.com", "<rds-endpoint>", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d+)?\b", lambda m: m.group(0) if m.group(0).startswith(("10.", "0.0.0.0", "127.")) else "<ip>", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text)
    return text

def aws(*args):
    r = subprocess.run(["aws", *args, "--profile", PROFILE, "--region", REGION, "--output", "json"],
                       capture_output=True, text=True)
    if r.returncode:
        return {"_error": r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit {r.returncode}"}
    return json.loads(r.stdout) if r.stdout.strip() else {}

def phys(stack, logical):
    d = aws("cloudformation", "describe-stack-resource", "--stack-name", STACKS[stack], "--logical-resource-id", logical)
    return d["StackResourceDetail"]["PhysicalResourceId"]

def save(name, title, cmd_desc, data):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"# {title}\n# Captured (UTC): {now}\n# Read-only command(s): {cmd_desc}\n# Redacted: account IDs, ARNs, resource IDs, IPs, hostnames.\n\n"
    body += json.dumps(data, indent=2, default=str)
    (OUT / name).write_text(redact(body) + "\n")
    print("wrote", name)

# 1. Stacks
stacks = {}
for k, s in STACKS.items():
    d = aws("cloudformation", "describe-stacks", "--stack-name", s)["Stacks"][0]
    res = aws("cloudformation", "list-stack-resources", "--stack-name", s)["StackResourceSummaries"]
    stacks[s] = {"StackStatus": d["StackStatus"], "Created": d["CreationTime"], "LastUpdated": d.get("LastUpdatedTime"),
                 "Resources": sorted(f'{r["LogicalResourceId"]} ({r["ResourceType"]}): {r["ResourceStatus"]}' for r in res)}
save("01-stacks.txt", "CloudFormation stacks and resources", "cloudformation describe-stacks; list-stack-resources", stacks)

# 2. Ingress: API Gateway integration + ALB
api_id = phys("ingress", "HttpApi")
api = aws("apigatewayv2", "get-api", "--api-id", api_id)
ints = aws("apigatewayv2", "get-integrations", "--api-id", api_id)["Items"]
routes = aws("apigatewayv2", "get-routes", "--api-id", api_id)["Items"]
alb_arn = phys("ingress", "InternalAlb")
alb = aws("elbv2", "describe-load-balancers", "--load-balancer-arns", alb_arn)["LoadBalancers"][0]
listeners = aws("elbv2", "describe-listeners", "--load-balancer-arn", alb_arn)["Listeners"]
tg_arn = phys("ingress", "AppHttpsTargetGroup")
tg = aws("elbv2", "describe-target-groups", "--target-group-arns", tg_arn)["TargetGroups"][0]
th = aws("elbv2", "describe-target-health", "--target-group-arn", tg_arn)["TargetHealthDescriptions"]
save("02-ingress.txt", "API Gateway HTTP API, VPC Link integration, internal ALB and target health",
     "apigatewayv2 get-api/get-integrations/get-routes; elbv2 describe-load-balancers/describe-listeners/describe-target-groups/describe-target-health",
     {"HttpApi": {k: api.get(k) for k in ["ProtocolType", "ApiEndpoint", "DisableExecuteApiEndpoint"]},
      "Routes": [r["RouteKey"] for r in routes],
      "Integrations": [{k: i.get(k) for k in ["IntegrationType", "ConnectionType", "IntegrationMethod", "TimeoutInMillis",
                                              "PayloadFormatVersion", "TlsConfig", "RequestParameters"]} for i in ints],
      "InternalAlb": {k: alb.get(k) for k in ["Scheme", "Type", "State", "AvailabilityZones", "SecurityGroups"]},
      "Listeners": [{k: l.get(k) for k in ["Port", "Protocol", "SslPolicy"]} for l in listeners],
      "TargetGroup": {k: tg.get(k) for k in ["Protocol", "Port", "HealthCheckProtocol", "HealthCheckPath", "HealthCheckIntervalSeconds",
                                             "HealthyThresholdCount", "UnhealthyThresholdCount", "Matcher"]},
      "TargetHealth": [{"Target": t["Target"]["Id"], "Port": t["Target"].get("Port"), "State": t["TargetHealth"]["State"],
                        "Reason": t["TargetHealth"].get("Reason")} for t in th]})

# 3. Compute: ASG + instances
asg_name = phys("app", "AppAutoScalingGroup")
asg = aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", asg_name)["AutoScalingGroups"][0]
worker_id = phys("base", "WorkerInstanceRecovery")
ids = [i["InstanceId"] for i in asg["Instances"]] + [worker_id]
inst = [i for r in aws("ec2", "describe-instances", "--instance-ids", *ids)["Reservations"] for i in r["Instances"]]
save("03-compute.txt", "Auto Scaling group and EC2 instances (app tier + worker)",
     "autoscaling describe-auto-scaling-groups; ec2 describe-instances",
     {"AutoScalingGroup": {k: asg.get(k) for k in ["MinSize", "MaxSize", "DesiredCapacity", "HealthCheckType",
                                                   "HealthCheckGracePeriod", "AvailabilityZones", "SuspendedProcesses"]},
      "AsgInstances": [{k: i.get(k) for k in ["InstanceId", "AvailabilityZone", "LifecycleState", "HealthStatus"]} for i in asg["Instances"]],
      "Instances": [{"InstanceId": i["InstanceId"], "Role": "worker" if i["InstanceId"] == worker_id else "web/api",
                     "InstanceType": i["InstanceType"], "State": i["State"]["Name"], "SubnetId": i.get("SubnetId"),
                     "HasPublicIp": bool(i.get("PublicIpAddress")), "IamInstanceProfile": "LabInstanceProfile" if "LabInstanceProfile" in str(i.get("IamInstanceProfile")) else "other",
                     "ImdsHttpTokens": i.get("MetadataOptions", {}).get("HttpTokens"),
                     "SecurityGroups": [g["GroupId"] for g in i.get("SecurityGroups", [])]} for i in inst]})

# 4. Network: security groups
sg_logicals = [("base", "AppSecurityGroup"), ("base", "WorkerSecurityGroup"), ("base", "DatabaseSecurityGroup"),
               ("ingress", "InternalAlbSecurityGroup"), ("ingress", "VpcLinkSecurityGroup"), ("ingress", "AppTargetSecurityGroup")]
sg_ids = {phys(s, l): l for s, l in sg_logicals}
sgs = aws("ec2", "describe-security-groups", "--group-ids", *sg_ids)["SecurityGroups"]
def rules(perms):
    out = []
    for p in perms:
        src = [x["CidrIp"] for x in p.get("IpRanges", [])] + [sg_ids.get(x["GroupId"], x["GroupId"]) for x in p.get("UserIdGroupPairs", [])] \
              + [x["PrefixListId"] for x in p.get("PrefixListIds", [])]
        out.append(f'{p.get("IpProtocol")} {p.get("FromPort", "all")}-{p.get("ToPort", "all")} <-> {src}')
    return out
save("04-security-groups.txt", "Security group rules (sources shown by CloudFormation logical name where internal)",
     "ec2 describe-security-groups",
     {sg_ids[g["GroupId"]]: {"Ingress": rules(g["IpPermissions"]), "Egress": rules(g["IpPermissionsEgress"])} for g in sgs})

# 5. Data: RDS, S3, SQS
db_id = phys("base", "Database")
db = aws("rds", "describe-db-instances", "--db-instance-identifier", db_id)["DBInstances"][0]
bucket = phys("base", "TemporaryInputBucket")
qurls = {l: aws("sqs", "get-queue-url", "--queue-name", phys("base", l).rsplit("/", 1)[-1])["QueueUrl"]
         for l in ["ExtractionQueue", "EmbeddingQueue", "ExtractionDlq", "EmbeddingDlq"]}
qattrs = {l: aws("sqs", "get-queue-attributes", "--queue-url", u, "--attribute-names", "All")["Attributes"] for l, u in qurls.items()}
objs = aws("s3api", "list-objects-v2", "--bucket", bucket, "--max-keys", "1000", "--query", "KeyCount")
save("05-data-stores.txt", "RDS PostgreSQL, temporary-input S3 bucket and SQS queues",
     "rds describe-db-instances; s3api get-public-access-block/get-bucket-encryption/get-bucket-lifecycle-configuration/get-bucket-policy-status/list-objects-v2 (KeyCount only); sqs get-queue-attributes",
     {"RDS": {k: db.get(k) for k in ["Engine", "EngineVersion", "DBInstanceClass", "MultiAZ", "PubliclyAccessible", "StorageEncrypted",
                                    "BackupRetentionPeriod", "LatestRestorableTime", "DeletionProtection", "AllocatedStorage", "StorageType",
                                    "DBInstanceStatus", "AvailabilityZone", "IAMDatabaseAuthenticationEnabled"]},
      "S3TemporaryInput": {"PublicAccessBlock": aws("s3api", "get-public-access-block", "--bucket", bucket).get("PublicAccessBlockConfiguration"),
                           "Encryption": aws("s3api", "get-bucket-encryption", "--bucket", bucket).get("ServerSideEncryptionConfiguration"),
                           "Lifecycle": aws("s3api", "get-bucket-lifecycle-configuration", "--bucket", bucket).get("Rules"),
                           "PolicyStatus": aws("s3api", "get-bucket-policy-status", "--bucket", bucket).get("PolicyStatus"),
                           "ObjectCountAtCapture": objs},
      "SQS": {l: {k: a.get(k) for k in ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible", "VisibilityTimeout",
                                        "MessageRetentionPeriod", "SqsManagedSseEnabled", "RedrivePolicy"]} for l, a in qattrs.items()}})

# 6. Secrets (names/metadata only, never values) and log groups
secrets = aws("secretsmanager", "list-secrets")
lgs = aws("logs", "describe-log-groups", "--log-group-name-prefix", "/inf2006/")["logGroups"]
save("06-secrets-and-logs.txt", "Secrets Manager metadata (no values retrieved) and CloudWatch log groups",
     "secretsmanager list-secrets (metadata only; get-secret-value NOT called); logs describe-log-groups",
     {"Secrets": [{"Name": s["Name"], "LastChangedDate": s.get("LastChangedDate"),
                   "RotationEnabled": s.get("RotationEnabled", False)} for s in secrets.get("SecretList", [])],
      "LogGroups": [{"Name": g["logGroupName"], "RetentionInDays": g.get("retentionInDays"), "StoredBytes": g.get("storedBytes")} for g in lgs]})

# 7. Alarms + history
alarms = aws("cloudwatch", "describe-alarms", "--alarm-name-prefix", "inf2006")["MetricAlarms"]
if not alarms:
    alarms = [a for a in aws("cloudwatch", "describe-alarms")["MetricAlarms"]]
hist = aws("cloudwatch", "describe-alarm-history", "--history-item-type", "StateUpdate", "--max-records", "50")
save("07-alarms.txt", "CloudWatch alarms and recent state-change history",
     "cloudwatch describe-alarms; describe-alarm-history --history-item-type StateUpdate",
     {"Alarms": [{k: a.get(k) for k in ["AlarmName", "StateValue", "StateReason", "StateUpdatedTimestamp", "Namespace", "MetricName",
                                        "Statistic", "Period", "EvaluationPeriods", "Threshold", "ComparisonOperator", "TreatMissingData"]}
                 | {"AlarmActionsConfigured": len(a.get("AlarmActions", []))} for a in alarms],
      "StateHistory": [{k: h.get(k) for k in ["AlarmName", "Timestamp", "HistorySummary"]} for h in hist.get("AlarmHistoryItems", [])]})
print("done")
