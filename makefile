#### 1. Makefile for managing Minikube cluster and services
autoscale-prime: 
	kubectl autoscale deployment prime-service-deployment --cpu-percent=50 --min=1 --max=10
build-service: 
	minikube -p=thesis image build -t prime-service:v1 ./services/prime-service
	minikube -p=thesis image build -t text-service:v1 ./services/text-service
	minikube -p=thesis image build -t frontend:v1 ./services/frontend
build-locust: 
	docker compose build locust
build-forecasting-service: 
	minikube -p=thesis image build -t forecasting-service:v1 ./forecasting-service
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


	#remember to change expose the ingress-nginx-controller svc. -- kubectl get svc -n ingress-nginx
deploy-service: 
	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml
	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml
deploy-forecasting-service:
	- kubectl apply -f ./k8s/forecasting-service.yaml
restart-forecasting-service:
	- kubectl apply -f k8s/forecasting-service.yaml
	- kubectl rollout restart deployment/forecasting-service-deployment
	- kubectl logs deploy/forecasting-service-deployment
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
configure-ingress-logging:
	kubectl patch configmap ingress-nginx-controller -n ingress-nginx --type merge --patch-file k8s/ingress-nginx-log-config-patch.yaml
	kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx
	kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=90s
deploy-monitor: 
	- kubectl apply -f k8s/monitor.yaml
restart-monitor: 
	- kubectl rollout restart deployment monitoring-stack-kube-prometheus-stack-grafana -n monitoring
	- kubectl rollout restart statefulset monitoring-stack-kube-prometheus-stack-kube-prom-prometheus -n monitoring
open-grafana: 
	- kubectl port-forward svc/monitoring-stack-grafana 3000:80 -n monitoring
open-prometheus: 
	- kubectl port-forward prometheus-monitoring-stack-kube-prom-prometheus-0  9090:9090 -n monitoring
restart-locust: 
	docker compose restart locust
deploy-locust: 
	docker compose up -d locust
open-locust: 
	@echo "Locust UI: http://localhost:8089"
ingress-request-counts:
	python3 helper/summarize_ingress_logs.py --input shares/ingress_raw.log --output shares/ingress_request_report.csv
capture-ingress-raw-logs:
	sh helper/capture_ingress_raw_logs.sh shares/ingress_raw.log
watch-ingress-request-counts:
	sh helper/watch_ingress_request_counts.sh ingress-backend shares/ingress_request_report.csv

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
# 	bash ./linux-script/enforce-machine-slice-cpuset.sh
# 	bash ./linux-script/lock-cpu-frequency.sh
stop-environment: 
	minikube -p=thesis stop
	bash ./linux-script/release-cpu-frequency.sh
