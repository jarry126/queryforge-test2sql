# QueryForge Kubernetes 轻量部署

这个目录提供 QueryForge API 的最小可运行 Kubernetes 清单，适合本地 Docker Desktop Kubernetes、minikube 或测试集群验证。

## 部署范围

当前只部署 QueryForge API：

```text
Kubernetes Deployment / Service / HPA
        |
        +--> 外部 PostgreSQL / Redis / Langfuse / LLM endpoint
```

PostgreSQL、Redis、Prometheus、Grafana、Langfuse 默认视为外部依赖，不在这套轻量清单中托管。

## 文件说明

| 文件 | 作用 |
|------|------|
| `namespace.yaml` | 创建 `queryforge` 命名空间 |
| `configmap.yaml` | 非敏感配置 |
| `secret.example.yaml` | Secret 模板，不要写真实密钥进仓库 |
| `deployment.yaml` | API Deployment，含 liveness/readiness/startup probe 与资源限制 |
| `service.yaml` | ClusterIP Service |
| `hpa.yaml` | CPU 70% 触发的轻量 HPA |
| `ingress.yaml` | 可选 Ingress，需要集群已有 ingress-nginx |
| `servicemonitor.yaml` | 可选 Prometheus Operator 采集配置 |
| `kustomization.yaml` | 基础可运行清单，不包含 Secret/Ingress/ServiceMonitor |

## 快速启动

1. 构建镜像：

```bash
docker build -t queryforge-text2sql:latest .
```

如果使用 minikube，需要把镜像构建到 minikube 的 Docker 环境中：

```bash
eval "$(minikube docker-env)"
docker build -t queryforge-text2sql:latest .
```

2. 创建 Secret：

```bash
cp deploy/k8s/secret.example.yaml deploy/k8s/secret.yaml
# 修改 deploy/k8s/secret.yaml 中的 __REQUIRED__ 占位符
kubectl apply -f deploy/k8s/secret.yaml
```

3. 修改非敏感配置：

所有可调参数都通过 Kubernetes 注入，不需要把配置写死到镜像里：

- 非敏感配置：修改 `deploy/k8s/configmap.yaml`，例如 `POSTGRES_HOST`、`REDIS_HOST`、`LLM_MODEL`、`RATE_LIMIT_QUERY`。
- 敏感配置：放到 `Secret`，例如 `OPENAI_API_KEY`、`DASHSCOPE_API_KEY`、数据库密码、`JWT_SECRET`。
- `deployment.yaml` 使用 `envFrom` 同时加载 `queryforge-config` 和 `queryforge-secret`，应用启动时会按环境变量读取。

4. 部署 API：

```bash
kubectl apply -k deploy/k8s
```

5. 查看状态：

```bash
kubectl -n queryforge get pods
kubectl -n queryforge get svc
kubectl -n queryforge logs deploy/queryforge-api
```

6. 本地端口转发验证：

```bash
kubectl -n queryforge port-forward svc/queryforge-api 8000:8000
curl http://localhost:8000/api/v1/live
curl http://localhost:8000/api/v1/ready
curl http://localhost:8000/metrics/
```

## 可选：Ingress

如果集群安装了 ingress-nginx，先修改 `ingress.yaml` 中的域名：

```yaml
host: queryforge.example.com
```

然后执行：

```bash
kubectl apply -f deploy/k8s/ingress.yaml
```

## 可选：Prometheus Operator

如果集群安装了 Prometheus Operator，可以应用 ServiceMonitor：

```bash
kubectl apply -f deploy/k8s/servicemonitor.yaml
```

如果没有 Prometheus Operator，普通 Prometheus 也可以通过 `deployment.yaml` 中的 `prometheus.io/*` annotations 抓取 `/metrics/`。

## 生产注意事项

- 不要把真实 Secret 提交到 Git。
- 生产镜像不要使用 `latest`，应替换成 Git SHA 或语义化版本。
- 生产建议 Redis 开启，因为全局限流与在途并发控制需要跨 Pod 共享状态。
- 横向扩容优先增加 Pod 副本，不建议单容器多 worker；如需多 worker，要额外处理 Prometheus multiprocess 指标与连接池总量。
- `POSTGRES_HOST` / `QUERY_POSTGRES_HOST` / `REDIS_HOST` 需要按真实环境修改为云服务地址或集群内 Service。
