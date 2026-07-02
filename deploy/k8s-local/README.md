# QueryForge 本地 Kubernetes overlay

这个 overlay 用于 Docker Desktop Kubernetes / kind 本地验证：只把 QueryForge API 放进 K8s，
PostgreSQL 和 Redis 继续复用本机 `docker compose` 中的服务，并通过 `host.docker.internal` 访问。

```bash
make infra-up

docker build -t queryforge-text2sql-app:k8s-local .

kubectl create namespace queryforge --dry-run=client -o yaml | kubectl apply -f -

kubectl -n queryforge create secret generic queryforge-secret \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=DASHSCOPE_API_KEY="$DASHSCOPE_API_KEY" \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=QUERY_POSTGRES_PASSWORD="${QUERY_POSTGRES_PASSWORD:-$POSTGRES_PASSWORD}" \
  --from-literal=REDIS_PASSWORD="${REDIS_PASSWORD:-}" \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}" \
  --from-literal=LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k deploy/k8s-local
kubectl -n queryforge rollout status deploy/queryforge-api
kubectl -n queryforge port-forward svc/queryforge-api 18000:8000

curl http://localhost:18000/api/v1/live
curl http://localhost:18000/api/v1/ready
curl http://localhost:18000/metrics/
```

如果本地 `.env` 已经配置好，也可以从 `.env` 生成 Secret，避免手动复制密钥：

```bash
tmp=$(mktemp /tmp/queryforge-secret.XXXXXX.env)
getv(){ grep -E "^$1=" .env | tail -1 | sed "s/^$1=//"; }
printf "OPENAI_API_KEY=%s\n" "$(getv OPENAI_API_KEY)" > "$tmp"
printf "DASHSCOPE_API_KEY=%s\n" "$(getv DASHSCOPE_API_KEY)" >> "$tmp"
printf "POSTGRES_PASSWORD=%s\n" "$(getv POSTGRES_PASSWORD)" >> "$tmp"
printf "QUERY_POSTGRES_PASSWORD=%s\n" "$(getv POSTGRES_PASSWORD)" >> "$tmp"
printf "REDIS_PASSWORD=%s\n" "$(getv REDIS_PASSWORD)" >> "$tmp"
printf "JWT_SECRET=%s\n" "$(getv JWT_SECRET)" >> "$tmp"
printf "LANGFUSE_PUBLIC_KEY=%s\n" "$(getv LANGFUSE_PUBLIC_KEY)" >> "$tmp"
printf "LANGFUSE_SECRET_KEY=%s\n" "$(getv LANGFUSE_SECRET_KEY)" >> "$tmp"
kubectl -n queryforge create secret generic queryforge-secret \
  --from-env-file="$tmp" \
  --dry-run=client -o yaml | kubectl apply -f -
rm -f "$tmp"
```

本地参数主要在 `configmap-patch.yaml` 中调整；敏感参数仍然走 `queryforge-secret`。
当前 overlay 默认让应用元数据库和业务查询库都指向本机 Docker Compose PostgreSQL，方便验证 K8s 启动链路。
如果要让 `/api/v1/query` 真正查到业务数据，需要把 `QUERY_POSTGRES_*` 改成有业务表的只读库，
或者先把测试表导入当前 PostgreSQL。
