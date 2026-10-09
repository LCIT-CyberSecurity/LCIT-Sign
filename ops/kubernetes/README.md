# Kubernetes deployment

Validated with `kubeconform -strict` (15 resources). Not exercised on a live
cluster from this repository: treat it as a reviewed starting point.

```bash
# 1. Build and push the two images to your registry, then edit the image
#    names in api.yaml and webui.yaml.
# 2. Edit config.yaml (public URL, OIDC issuer/client, bootstrap admin) and
#    ingress.yaml (host, TLS secret name).
# 3. Create the namespace, then the secret (see secret.example.yaml):
kubectl apply -f ops/kubernetes/namespace.yaml
kubectl -n lcit-sign create secret generic lcit-sign-secrets \
  --from-literal=master_key="$(openssl rand -base64 48)" \
  --from-literal=session_secret="$(openssl rand -base64 48)" \
  --from-literal=oidc_client_secret='<from your identity provider>' \
  --from-literal=db_password="$(openssl rand -base64 24 | tr -d '/+=')"
# 4. TLS secret for the Ingress (or use cert-manager):
kubectl -n lcit-sign create secret tls lcit-sign-tls --cert=tls.crt --key=tls.key
# 5. Apply:
kubectl apply -k ops/kubernetes/
```

Design notes

- **Secrets** are mounted as files and read through `LCIT_SIGN_*_FILE`; none
  is in the ConfigMap or an environment variable. **Back up `master_key`
  separately** from the database and volume backups.
- **TLS** ends at the Ingress. `ops/admin/certificate-installer.sh` is for the
  Docker deployment; here you rotate the `lcit-sign-tls` Secret (or let
  cert-manager do it).
- **One API replica, `Recreate` strategy.** The API runs the reminder, renewal,
  notification and directory-sync worker in-process, keeps its rate limiter in
  memory and applies database migrations at start. Scale the web tier, not the API.
- **Files** live on a `PersistentVolumeClaim` (`lcit-sign-data`): no S3 or
  MinIO dependency. Snapshot it together with PostgreSQL.
- **PostgreSQL** here is a single StatefulSet for convenience; prefer a
  managed or operator-run instance in production and change
  `LCIT_SIGN_DATABASE_URL`.
- **NetworkPolicy** denies ingress by default and allows only
  ingress controller → web, web → API, API → PostgreSQL. Egress is open (the
  API must reach the OIDC provider, SMTP/Graph and directory APIs).
- The API pod is non-root with a read-only root filesystem; the nginx web pod
  needs its default (writable) filesystem and a few capabilities.
