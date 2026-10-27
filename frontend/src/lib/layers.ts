export type Status = "ran" | "mock" | "offline" | "ci";

export interface Layer {
  id: string;
  name: string;
  tech: string;
  what: string;
  status: Status;
  statusLabel: string;
  path: string;
}

export const REPO = "https://github.com/tanvir-ux/ai-engineering-stack";

export const STATUS_TEXT: Record<Status, string> = {
  ran: "Ran for real",
  mock: "Tested with a mock",
  offline: "Validated offline",
  ci: "Checked in CI",
};

export const LAYERS: Layer[] = [
  {
    id: "frontend",
    name: "Front end",
    tech: "React, TypeScript, Vite",
    what: "Chat screen that streams the answer word by word and asks you to approve risky actions.",
    status: "ran",
    statusLabel: "Ran for real",
    path: "frontend",
  },
  {
    id: "auth",
    name: "Login and permissions",
    tech: "OIDC, PKCE, JWT, RBAC",
    what: "Sign in, then every request carries a signed token. Roles decide which documents and tools you may use.",
    status: "ran",
    statusLabel: "Ran for real (mock identity provider)",
    path: "src/aistack/auth",
  },
  {
    id: "gateway",
    name: "API gateway",
    tech: "FastAPI, rate limits, tracing",
    what: "The single front door. Checks the token, limits abuse and streams events back.",
    status: "ran",
    statusLabel: "Ran for real",
    path: "src/aistack/gateway",
  },
  {
    id: "orchestration",
    name: "Orchestration",
    tech: "LangGraph",
    what: "A step-by-step workflow with saved checkpoints. It pauses for a human before it changes anything.",
    status: "ran",
    statusLabel: "Ran for real",
    path: "src/aistack/orchestration",
  },
  {
    id: "agent",
    name: "Agent",
    tech: "OpenAI Agents SDK",
    what: "Decides whether to answer from documents or call a tool. The model sits behind an interface.",
    status: "ran",
    statusLabel: "Ran for real (deterministic stand-in model)",
    path: "src/aistack/agents",
  },
  {
    id: "mcp",
    name: "Tools over MCP",
    tech: "FastMCP",
    what: "Company tools (create a ticket, ticket statistics) served over the Model Context Protocol, with the user's token.",
    status: "ran",
    statusLabel: "Ran for real",
    path: "src/aistack/mcp_tools",
  },
  {
    id: "retrieval",
    name: "Search",
    tech: "FAISS, BM25, reranking, Pinecone",
    what: "Finds the right passages, but only among documents you are allowed to see.",
    status: "ran",
    statusLabel: "Ran locally. Pinecone adapter mock-tested",
    path: "src/aistack/retrieval",
  },
  {
    id: "data",
    name: "Data lakehouse",
    tech: "PySpark, Delta, Databricks, Snowflake",
    what: "Cleans raw documents and tickets into tidy tables. Spark ran locally. Databricks and Snowflake code is validated, not run on a live account.",
    status: "offline",
    statusLabel: "Spark ran. Databricks and Snowflake not executed live",
    path: "src/aistack/data",
  },
  {
    id: "evals",
    name: "Observability and evals",
    tech: "OpenTelemetry, Langfuse, eval harness",
    what: "Traces every request and measures search quality with real numbers.",
    status: "ran",
    statusLabel: "Ran for real",
    path: "docs/EVAL_REPORT.md",
  },
  {
    id: "production",
    name: "Production",
    tech: "Docker, Kubernetes, Helm, Terraform, GitHub Actions",
    what: "Container images, cluster manifests and an AWS sketch, all linted. CI builds and tests on every push.",
    status: "ci",
    statusLabel: "Linted offline. Compose checked in CI",
    path: "deploy",
  },
];
