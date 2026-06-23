# Take-Home Assignment: AWS Infrastructure for a Security Scanning Platform

## Background

A security team runs on-demand network scans against external targets — think port discovery and service fingerprinting. Analysts submit scan requests through an internal API, the results are processed asynchronously, and every completed scan generates an audit event that feeds downstream compliance workflows.

The engineering team has already built and tested the application locally. It works. The problem is that it currently runs on a single developer's laptop. The team needs it deployed to AWS in a way that is repeatable, secure, and ready to hand off to an operations team.

You are joining as the platform engineer responsible for taking this application to production.

---

## Your Task

Design, provision, and operate the complete AWS infrastructure required to run this application. All infrastructure must be written as code. The application source is provided — your focus is entirely on the platform beneath it.

At the end of this assignment we expect to see four things working together:

1. **AWS infrastructure provisioned as code** — VPC, compute, networking, and any supporting resources created entirely via Terraform (or equivalent). Nothing created by hand in the console.
2. **A self-managed Kubernetes cluster** running on EC2, with the application deployed and the API reachable from outside the cluster.
3. **A CI/CD pipeline with a self-hosted runner** — automated image builds, infrastructure validation, and deployment to the cluster on every merge to main. The runner itself must run inside your infrastructure, not on a cloud-hosted runner.
4. **Network segmentation enforced in depth** — certain workloads have internet access, others are completely isolated, and all permitted egress flows through a controlled path you own.

---

## The Application

The provided application (`services/`) consists of four containerized components:

| Service | Role | Internet required |
|---|---|---|
| `api` | Accepts scan requests over HTTP (`POST /scans`) | Yes |
| `scanner` | Runs `nmap` against the submitted target | Yes |
| `results-processor` | Subscribes to RabbitMQ, writes each scan result to a local SQLite database | **No** |
| `rabbitmq` | Message broker (fanout exchange `scan.results`) | **No** |

You can run the stack locally to understand its behaviour before designing the platform:

```bash
cp .env.example .env
docker compose up --build

# Submit a test scan
curl -s -X POST http://localhost:8080/scans \
  -H 'Content-Type: application/json' \
  -d '{"target": "scanme.nmap.org", "scan_type": "port_scan"}' | jq

# Watch the results-processor consume and store the result
docker compose logs -f results-processor
```

Read the service source in `services/` to understand message schemas, queue/exchange names, and environment variables before writing your deployment manifests.

---

## Security Context

This platform runs active network scans against external targets. That makes it an attractive target and a potential weapon if misconfigured — a compromised scanner could be used to probe internal systems or launch scans against arbitrary hosts.

Several constraints follow from this directly:

- **Blast radius must be limited.** Not every component needs internet access. A results-processor that can reach the public internet is a misconfiguration, not a feature. Isolation must be enforced at the infrastructure level, not by convention or documentation.
- **Egress must be controlled and auditable.** Outbound traffic from permitted workloads should flow through a single choke point that can be monitored, restricted by destination, and replaced without touching application code.
- **Credentials must never live in code or images.** The application consumes RabbitMQ credentials and potentially AWS credentials. How those secrets reach running containers is part of your design.
- **The API is a public surface.** It accepts scan targets from callers. An attacker who can influence the target field could trigger scans against internal infrastructure. The application has a basic guard — your network design should make exploitation harder even if the application guard fails.

Security is not a separate workstream here. It is embedded in the networking design, the cluster configuration, and the CI/CD pipeline.

---

## CI/CD Context

The team currently has no automated pipeline. Deployments happen manually, there is no image scanning, and nobody knows whether the Terraform state matches what is actually running.

As part of this assignment, implement a CI/CD pipeline that treats infrastructure and application as a single system:

- **Container images** should be built, scanned for vulnerabilities, and pushed to a registry on every change.
- **Infrastructure changes** should be validated (`terraform plan`) on pull requests and applied automatically on merge to the main branch.
- **Application deployments** should be triggered by image changes without requiring manual kubectl commands.
- **The runner must be self-hosted** and run inside your infrastructure — not on a cloud-provided runner. This is intentional: it tests your ability to provision and operate CI infrastructure, not just write pipeline definitions.
- **The pipeline itself is a security control.** It should be the only path by which new code reaches the cluster — no out-of-band applies, no manually pushed images.

You do not need a fully productionised pipeline with every bell and whistle. You do need one that demonstrates the principle: every change goes through automation, and the automation enforces the rules humans forget.

---

## Requirements

### 1. Infrastructure as Code

Provision all AWS resources using IaC (Terraform preferred). No manual console steps. The full environment must be reproducible from a single `terraform apply`.

### 2. Self-managed Kubernetes

Deploy a Kubernetes cluster on EC2 **without using EKS or any other managed Kubernetes service**. You choose the bootstrapping tool (kubeadm, k3s, RKE2, or similar) and justify the choice.

### 3. Application Deployment

Deploy all four application components and RabbitMQ into the cluster. Use Kubernetes-native manifests, Helm charts, or Kustomize — your choice. The API must be reachable from outside the cluster.

### 4. CI/CD Pipeline with Self-hosted Runner

Implement an automated pipeline that covers the full delivery lifecycle:

- Build and scan container images on every commit.
- Validate infrastructure changes on pull requests; apply on merge to main.
- Deploy updated images to the cluster without manual intervention.

The pipeline runner must be provisioned as part of your infrastructure and run inside the cluster or on a dedicated EC2 instance — not on a managed CI runner. Include the runner setup in your IaC and document how to register it.

### 5. Event-driven Scaling

The scanner workload is bursty. Implement autoscaling that reacts to workload demand: when unconsumed messages in `scan.jobs` exceed a threshold, additional scanner replicas should start; when the queue drains, replicas should scale back down. Do not rely solely on CPU/memory metrics for this. Choose your own tooling and justify the decision.

### 6. Network Segmentation and Egress Control

This is the most heavily weighted requirement. The application's connectivity rules must be enforced at the infrastructure level, not just by convention:

- `api` and `scanner` require outbound internet access.
- `results-processor` and `rabbitmq` must be **completely isolated** from the internet — they may only communicate within the cluster.
- All outbound internet traffic from permitted workloads must flow through a **single, controlled egress path** that you own and operate.
- **You may not use AWS NAT Gateway, AWS NAT Instance AMIs provided by AWS, or any other managed AWS egress service** to fulfil this requirement. Build and operate the egress component yourself.
- Enforce the isolation using Kubernetes NetworkPolicy in addition to any VPC-level controls.

### 7. Observability

The cluster and application must be observable without SSHing into nodes. At minimum:

- Cluster and node metrics (CPU, memory, disk)
- Application-level metrics (scan request rate, queue depth, scan duration)
- Centralised log aggregation from all pods
- A dashboard or query interface that lets you answer: *"How many scans completed in the last hour, and how many failed?"*

---

## Deliverables

```
infra/
  terraform/        # All AWS resource definitions
  kubernetes/       # Manifests, Helm values, or Kustomize overlays
  ci/               # Pipeline definition and self-hosted runner provisioning
  docs/
    architecture.md # Design decisions and security model
    operations.md   # Deploy, scale, upgrade, and troubleshoot runbook
    tradeoffs.md    # What you'd do differently with more time
```

Each area must be present and functional. Partial work should be documented in `tradeoffs.md` — an honest gap analysis is valued over something that looks complete but doesn't work.

---

## Evaluation Criteria

| Area | Weight |
|---|---|
| Egress architecture — correctness, isolation enforcement, no managed shortcuts | 25% |
| Kubernetes operational knowledge — cluster setup, workload config, health probes | 20% |
| Infrastructure design and IaC quality | 15% |
| CI/CD pipeline and self-hosted runner | 15% |
| Event-driven scaling implementation | 10% |
| Observability depth and usefulness | 10% |
| Documentation clarity and technical honesty | 5% |

---

## Constraints

- Target region: `eu-west-1` (or state your choice in the architecture doc).
- Use only the AWS free tier or the smallest viable instance types — we will not run this at scale.
- No hardcoded credentials anywhere in the repository. Use a `.env.example` pattern or AWS IAM roles.
- `scanme.nmap.org` is the only acceptable scan target in any demo or test.

---

## Questions

State any assumptions in `docs/architecture.md` and proceed. We value confident, well-reasoned decisions over requests for clarification on every ambiguity.
