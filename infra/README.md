# Terraform — Infrastructure as Code

Describe in code all the resources that were clicked together by hand in the AWS Console. Build or tear them down with a single command.

## Files
- `main.tf` — all resources: networking/security groups, SQS+DLQ, RDS, IAM, the 3 Lambdas, the SQS trigger, API Gateway
- `variables.tf` — values that aren't hardcoded (db_password, etc.)
- `outputs.tf` — prints the API address, RDS address, etc. after apply

The comment on each resource block notes which manual step it corresponds to.

## How to run it (when you actually want to deploy)
Prerequisites: (1) install Terraform; (2) configure AWS credentials (`aws configure` or environment variables); (3) have the 3 zips in the same directory (get-order.zip / create-order.zip / generate-plan.zip)

```bash
cd infra
terraform init                 # download the aws provider
terraform plan                 # preview what will be created (no real changes)
terraform apply                # actually create (will prompt for db_password; costs money: RDS)
# ... test against the api_url returned by terraform output ...
terraform destroy              # tear everything down in one command, stop billing
```

## Manual vs. Terraform
| | Manual | Terraform |
|---|---|---|
| Create | Lots of clicking in the Console, easy to miss something | One command: `terraform apply` |
| Delete | Delete one by one, risk of deleting the wrong thing or leaving leftovers | `terraform destroy` removes everything cleanly |
| Record | All lives in the console, forgotten in a couple of days | Configuration lives in code, in Git, versioned |
| Switch account/environment | Click through it all again | Apply the same code again |

Interview: "What is Infrastructure as Code?" → Defining infrastructure in code rather than clicking by hand, so the configuration can go into Git, be versioned, repeated, and torn down in one command.

## Network architecture (why it can really run a real LLM)
This Terraform builds a **dedicated VPC** (not the default VPC), in a standard production layout:
- **Public subnets** (2): host the **NAT Gateway** (with an EIP), routing → IGW
- **Private subnets** (2): host **Lambda + RDS**, routing 0.0.0.0/0 → NAT
- **SQS** goes over a **VPC Interface Endpoint** (private connectivity — cheaper/more secure than going through the NAT)
- **The Claude API (third party, no VPC Endpoint)** goes out to the internet via the **NAT** ← this is the key to actually running a real LLM

So when `LLM_PROVIDER=claude`, generate-plan can reach Claude (through the NAT) even from a private subnet. For a cheap demo, use `LLM_PROVIDER=mock` (no outbound traffic).

Running a real LLM:
```bash
terraform apply -var db_password=... -var anthropic_api_key=sk-ant-... -var llm_provider=claude
```

> Interview soundbite: "A Lambda inside a VPC reaches AWS services through a VPC Endpoint, and reaches the internet / third-party APIs through a NAT Gateway."
> ⚠️ A NAT Gateway costs about $0.045/hour (plus data transfer); always `terraform destroy` when you're done.

## RAG on AWS (working locally, the cloud-side IaC is in place but there are two gaps to fill)

Locally, RAG = pgvector (a Postgres extension) + fastembed (a local ONNX model). Moving it to AWS differs from the local setup in two places, both flagged in the Terraform:

1. **pgvector extension**: RDS PostgreSQL ≥15.2 has pgvector built in, and `engine_version` is pinned to `16.4`. You enable it with `CREATE EXTENSION vector` (in migration `0002_rag.py`).
2. **embedding provider**: Lambda has a 250MB unzipped limit; fastembed's ONNX model (~100MB+) fits but is slow to cold-start and inelegant → in production, switch to a **cloud embedding API** (Voyage / OpenAI; Anthropic has no embedding model). The Terraform controls this with `var.embed_provider`, defaulting to `mock`.

⚠️ **Two gaps to fill (recorded honestly — and good "I know where the gaps are" talking points for interviews):**
- **Table/extension bootstrap**: on AWS, the Lambda cold start uses `Base.metadata.create_all` to create tables, which **does not reach** the raw SQL in migration `0002` (`CREATE EXTENSION vector` + the `knowledge_chunks` table). So once RDS is up, you need a **one-off bootstrap**: connect to the database and run `alembic upgrade head` (or manually `CREATE EXTENSION vector` + create the table), then seed the knowledge base (`seed_knowledge.py`). This could be done as a one-off bootstrap Lambda or an RDS init script.
- **Cloud embedder code**: `embedding_service.py` currently has only `MockEmbedder` / `FastEmbedEmbedder`. To produce real retrieval scores on AWS, you need to add a `VoyageEmbedder` (calling the API, with the dimension aligned to 384 — or correspondingly change `knowledge_chunks`'s `vector(N)`), and inject `VOYAGE_API_KEY` into generate-plan in the Terraform (a placeholder is already left in the main.tf comments).

> Interview soundbite: "Locally I validated RAG end to end with fastembed — the retrieval layer is gated in CI at recall@3 ≥ 0.80; the generation layer uses a claim-level, NLI-style three-way judgement (supported/neutral/contradicted), where the load-bearing results are that grounding coverage separates cleanly between in-knowledge-base and out-of-knowledge-base cases (the latter scoring zero, which is usable as an out-of-scope detector) and that 5 of 5 planted contradictions are caught, so the near-zero contradiction rate reflects a judge that actually fires. Moving to the cloud swaps in pgvector on RDS + a cloud embedding API — the retrieval logic (the shared `services.process_care_plan`) doesn't change by a single line; only the provider and the bootstrap table-creation step change."
>
> Current measured values live in the root [`README.md`](../README.md#two-layer-evaluation-the-part-id-defend-in-an-interview) — that is the single source of truth. Don't restate the decimals here: the judge is a live LLM, so they drift run to run, and this file previously carried figures from an older 5-case eval.
