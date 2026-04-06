#### 1. Makefile for managing Minikube cluster and services
autoscale-prime: 
	kubectl autoscale deployment prime-service-deployment --cpu-percent=50 --min=1 --max=10
build-service: 
	minikube -p=thesis image build -t prime-service:v1 ./services/prime-service
	minikube -p=thesis image build -t text-service:v1 ./services/text-service
	minikube -p=thesis image build -t frontend:v1 ./services/frontend
build-locust: 
	docker compose build locust-master locust-worker
start:
	minikube -p=thesis start --driver=kvm2 --container-runtime=containerd --nodes=1 --cpus=6 --memory=8192

	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml

	# Wait for the Nginx controller pods to be ready
	kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=90s

	# Now apply your ingress rules
	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml

deploy-service: 
	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml
	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml
restart-service: 
	- kubectl rollout restart deployment prime-service-deployment
	- kubectl rollout restart deployment text-service-deployment
	- kubectl rollout restart deployment frontend-deployment
install-helm-monitor: 
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	kubectl create namespace monitoring
	helm install monitoring-stack prometheus-community/kube-prometheus-stack -n monitoring
install-helm-ingress: 
	helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
	helm repo update
	helm install ingress-nginx ingress-nginx/ingress-nginx \
	--namespace ingress-nginx --create-namespace \
	--set controller.metrics.enabled=true \
	--set controller.metrics.serviceMonitor.enabled=true \
	--set controller.metrics.serviceMonitor.additionalLabels.release="monitoring-stack"

# # This ensures metrics, the ServiceMonitor for Prometheus, and stub-status are all ON
# helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
#   -n ingress-nginx \
#   --set controller.metrics.enabled=true \
#   --set controller.metrics.serviceMonitor.enabled=true \
#   --set controller.metrics.serviceMonitor.additionalLabels.release="monitoring-stack"
deploy-monitor: 
	- kubectl apply -f k8s/monitor.yaml
restart-monitor: 
	- kubectl rollout restart deployment monitoring-stack-kube-prometheus-stack-grafana -n monitoring
	- kubectl rollout restart statefulset monitoring-stack-kube-prometheus-stack-kube-prom-prometheus -n monitoring
open-grafana: 
	- kubectl port-forward svc/monitoring-stack-grafana 3000:80 -n monitoring
open-prometheus: 
	- kubectl port-forward prometheus-monitoring-stack-kube-prom-prometheus-0  9090:9090 -n monitoring
stop:
	- kubectl port-forward prometheus-monitoring-stack-kube-prom-prometheus-0  9090:9090 -n monitoring
restart-locust: 
	docker compose restart locust-master locust-worker
deploy-locust: 
	docker compose up -d locust-master locust-worker
open-locust: 
	@echo "Locust UI: http://localhost:8089"

test-pod:
	kubectl run -it busybox --image=busybox --restart=Never -- sh
tss-build: 
	minikube -p=thesis image build -t custom-scaling-server:latest ./helper/custom-scaling-server
tss-deploy: 
	kubectl apply -f k8s/custom-scaling-server.yaml
#curl -X PUT http://localhost:1208?n=5
#### 2. Makefile for managing Minikube cluster and services with cgroup adjustments
start-environment: 
	$(MAKE)	start
	bash ./linux-script/enforce-machine-slice-cpuset.sh
	bash ./linux-script/lock-cpu-frequency.sh
stop-environment: 
	minikube -p=thesis stop
	bash ./linux-script/release-cpu-frequency.sh
