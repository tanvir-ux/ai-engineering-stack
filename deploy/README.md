# Deployment

Four ways to run the stack, from laptop to cloud. Status of each is stated plainly, because "has a Dockerfile" is not the same as "has been deployed".

| Target | Files | Status |
| --- | --- | --- |
| Laptop, no containers | `make dev-stack` | **Executed** on the build machine |
| Docker Compose | [`docker-compose.yml`](../docker-compose.yml), [`docker/`](docker) | **Built and smoke-tested in CI only.** There was no Docker on the build machine |
| Kubernetes | [`helm/aistack`](helm/aistack), rendered to [`k8s/aistack.yaml`](k8s/aistack.yaml) | **Linted and schema-validated, never applied to a cluster** |
| AWS | [`terraform/`](terraform) | **`terraform validate` only, never applied** |

## Images

`docker/Dockerfile.api` builds one Python image used for two services: the gateway (`aistack serve`) and the MCP tool server (`aistack mcp`). `docker/Dockerfile.web` builds the React app and serves it from an unprivileged nginx on port 8080.

Hardening that is in the files: non-root user, read-only root filesystem (compose and Kubernetes), all Linux capabilities dropped, `no-new-privileges`, a health check on every container, and no secrets baked into any image.

The Helm values point at `ghcr.io/tanvir-ux/ai-engineering-stack-api` and `...-web`. **Those images are not published.** Build and push your own, then set `image.api`, `image.web` and `image.tag`.

## Compose

```bash
docker compose up --build
open http://localhost:8080/?live=http://localhost:8000
python scripts/compose_smoke.py --base http://localhost:8000 --web http://localhost:8080
```

The smoke script signs in through the real PKCE flow, asks a question, creates a ticket that needs approval, approves it, and checks that the web page is served. The `docker` job in CI does exactly this.

## Kubernetes

The chart is the source of truth. The rendered manifest in `k8s/aistack.yaml` is committed for people who do not use Helm, and CI fails if it differs from `helm template`.

```bash
make k8s-render       # regenerate deploy/k8s/aistack.yaml
make k8s-validate     # helm lint + kubeconform --strict
```

What the chart provides: separate Deployments for api, mcp and web; readiness (`/ready`) and liveness (`/health`) probes; a HorizontalPodAutoscaler for the API; an Ingress with TLS; a NetworkPolicy so that only the API can reach the MCP server; resource requests and limits; and a ConfigMap for non-secret settings.

The mock identity provider is on by default so the chart runs without anything else. **For production set `config.idpMode: external`** and point `oidcIssuer` at your provider (Keycloak, Auth0 or Entra ID).

Rate limiting is per replica. For a real limit, also set one at the ingress.

## Secrets

- No secret is committed. `.env` is git-ignored and `.env.example` holds names only.
- The Helm chart never creates or reads secret values. It references an existing Secret (default name `aistack-secrets`) with the optional keys `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PINECONE_API_KEY` and `AISTACK_MCP_INTERNAL_SECRET`:

  ```bash
  kubectl create secret generic aistack-secrets \
    --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"
  ```
- The Terraform sketch creates empty AWS Secrets Manager entries. Values are set outside Terraform.
- Tokens are never written to the checkpoint database. A test (`test_token_is_not_persisted_in_checkpoints`) enforces it.
- The mock IdP's signing key is generated at start-up. Set `AISTACK_IDP_KEY_FILE` only for local development, and never commit it (`*.pem` is ignored).

## AWS (Terraform sketch)

ECR repositories, an ECS Fargate service behind an ALB, Secrets Manager containers and a CloudWatch log group. The api and mcp containers share one task so the MCP server is only reachable on localhost.

```bash
make tf-validate
cd deploy/terraform && terraform plan -var 'name=aistack'   # needs AWS credentials; I have not run this
```

It uses the default VPC, has no autoscaling and no remote state. Treat it as a starting point.

## Runbook

| Symptom | Check |
| --- | --- |
| Pod not ready | `GET /ready` returns 503 until the workflow graph is built and the signing keys can be fetched. The response body lists which check failed |
| 401 from `/chat` | The token issuer must equal `AISTACK_OIDC_ISSUER`, and the MCP server must reach `AISTACK_OIDC_JWKS_URL` |
| Browser blocked by CORS | Add the web origin to `AISTACK_CORS_ORIGINS` (a JSON list) |
| Login redirect refused | Add the prefix to `AISTACK_OIDC_REDIRECT_PREFIXES` |
| 429 | The per-user rate limit (`AISTACK_RATE_LIMIT_PER_MINUTE`) was hit |
| A paused approval was lost | Checkpoints are in `AISTACK_CHECKPOINT_DB`. Mount it on a persistent volume, or move to a database-backed saver |

Rollback: `helm rollback aistack <revision>`, or redeploy the previous image tag. The service is stateless apart from the checkpoint file.
