rsync -avz --progress \
  --exclude ".git/" \
  --exclude "__pycache__/" \
  --exclude ".pytest_cache/" \
  --exclude ".venv/" \
  --exclude "venv/" \
  --exclude "node_modules/" \
  --exclude "dist/" \
  --exclude "build/" \
  --exclude ".next/" \
  --exclude "*.pyc" \
  --exclude "*.log" \
  --exclude "shares/" \
  --exclude "work-log/" \
  ./ k3s-master:~/predictive-autoscaling-k8s-test/