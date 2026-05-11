# OKE 50-Person Hands-On Demo Runbook

This runbook is for a room of about 50 concurrent attendees using the
OpenTofu-managed Kubernetes deployment of AI Optimizer. It assumes attendees
will use the Streamlit client, embed small documents, and try LLM-only,
Vector Search, NL2SQL, and combined-tool chatbot flows.

## Deployment Flow

First apply the normal OpenTofu Kubernetes stack for the target environment:

```bash
cd opentofu
tofu init
tofu plan
tofu apply
```

After the IaC apply completes, apply the demo capacity overlay with Helm:

```bash
helm upgrade --install <release> ./helm \
  --namespace <namespace> \
  --reuse-values \
  --values helm/examples/values-oke-demo-50.yaml
```

Use the release name and namespace created by the OpenTofu deployment. The
overlay is intentionally separate from OpenTofu so the same deployment can be
retuned for a different room size by copying and editing the values file.

The 50-person overlay sets:

- `server.maxClients: 150`
- `AIO_DB_POOL_SIZE: "20"`
- explicit server/client CPU and memory requests and limits
- less aggressive Streamlit client liveness/readiness probe timeouts

For a smaller or larger workshop, copy `helm/examples/values-oke-demo-50.yaml`
to a new file and adjust `server.maxClients`, `AIO_DB_POOL_SIZE`, pod
resources, node pool size, and database capacity together.

## Critical Routing Constraint

Keep `server.replicaCount: 1` for this demo unless sticky routing has been
configured and tested. The embed workflow stores uploaded local files on a
per-pod `emptyDir`; the upload request and the follow-up `/v1/embed/` request
must hit the same server pod.

Scaling the client pod is also optional. Streamlit sessions are stateful, so
only scale the client after verifying the ingress/load balancer keeps each
browser session stable.

## Pre-Demo Checklist

Complete this before attendees join:

- Confirm all pods are ready and have no restarts.
- Open the client UI and confirm a unique client ID appears in the About menu.
- Configure and test the chat model and embedding model.
- Create or import one small vector store that everyone can use.
- Run one successful query for each route: LLM-only, Vector Search, NL2SQL,
  and combined Vector Search + NL2SQL.
- Run one small local document embed from the UI and wait for terminal status.
- Confirm SQLcl MCP tools are available for NL2SQL.
- Confirm the Autonomous Database has CPU autoscaling enabled and enough session
  headroom for the larger pool.
- Keep SigNoz or Kubernetes metrics visible during the session.

## Attendee Guidance

Use a constrained exercise flow:

1. Start with LLM-only chat.
2. Switch to Vector Search using the pre-created vector store.
3. Try NL2SQL against the prepared database.
4. Try combined tools.
5. Embed only the provided small sample document.

Avoid open-ended uploads during the first pass. If attendees bring arbitrary
large PDFs, embedding can saturate CPU, database sessions, and external
embedding-provider rate limits.

## Live Monitoring

Watch these signals during the demo:

- Server and client pod restarts.
- Server CPU and memory saturation.
- Client probe failures or restarts.
- Autonomous Database sessions and CPU.
- Embed job failures in the UI and server logs.
- Provider rate-limit errors from chat or embedding calls.
- Slow `/v1/readiness` or `/v1/embed/jobs/{job_id}` polling.

If the room stalls, pause new embedding jobs first. Chat-only traffic is easier
to recover than a backlog of concurrent parse/chunk/embed/index jobs.
