# Deploying TaxRAG on AWS

One container image, one S3 bucket, one Fargate service, one scheduled Fargate task.
Nothing here is AWS-specific inside the application; swap ECS for any Docker host.

```bash
# 1. Build + push the image
aws ecr create-repository --repository-name taxrag
docker build -t taxrag tax-rag/
docker tag taxrag:latest <acct>.dkr.ecr.us-east-1.amazonaws.com/taxrag:latest
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.us-east-1.amazonaws.com
docker push <acct>.dkr.ecr.us-east-1.amazonaws.com/taxrag:latest

# 2. (optional) store the Anthropic key
aws secretsmanager create-secret --name taxrag/anthropic --secret-string '<key>'

# 3. Deploy
aws cloudformation deploy --stack-name taxrag --template-file tax-rag/deploy/aws/template.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides ImageUri=<acct>.dkr.ecr.us-east-1.amazonaws.com/taxrag:latest \
      VpcId=vpc-... SubnetIds=subnet-a,subnet-b AnthropicApiKeySecretArn=<arn-or-empty>

# 4. Seed the bucket with the index built locally (or let the nightly task build it)
export TAXRAG_S3_BUCKET=$(aws cloudformation describe-stacks --stack-name taxrag --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" --output text)
cd tax-rag && taxrag sync push
```

* The API task runs `taxrag sync pull` on start, so a fresh index is picked up on every deploy/restart.
* The ingest task runs nightly (`IngestSchedule`): pull index → crawl live listings + the existing
  `Forms` DynamoDB table / `forms123456` archive → push index. Idempotent, so running it twice is harmless.
* Without an Anthropic key the task role has `bedrock:InvokeModel` and the app falls back to Bedrock Claude
  (same path `IRS-Forms/ai_summary.py` uses). Set `TAXRAG_LLM_PROVIDER` explicitly to force one.
* Put an ALB (OIDC/Cognito) in front of the service before exposing it beyond the VPC; the security group
  only admits 10.0.0.0/8 by default.
* To trigger ingestion from the existing `New_IRS_Forms` Lambda instead of a schedule, have it call
  `ecs.run_task` with `IngestTaskDefinition` (output above) at the end of a run.

Sizing: 1 vCPU / 4 GB serves the Phase 1–3 index; ingestion of the full seed corpus takes ~1 h on 2 vCPU.
Moving the store to Postgres/pgvector (RDS) is described in `docs/POSTGRES_MIGRATION.md`.
