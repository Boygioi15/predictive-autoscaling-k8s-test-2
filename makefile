#### 1. Makefile for managing Minikube cluster and services
autoscale-prime: 
	kubectl autoscale deployment prime-service-deployment --cpu-percent=50 --min=1 --max=10
build-service: 
	minikube -p=thesis image build -t prime-service:v1 ./services/prime-service
	minikube -p=thesis image build -t text-service:v1 ./services/text-service
	minikube -p=thesis image build -t frontend:v1 ./services/frontend
build-locust: 
	minikube -p=thesis image build -t locust-test:v1 ./locust-test
start:
	minikube -p=thesis start --driver=kvm2 --container-runtime=containerd --nodes=1 --cpus=6 --memory=8192

	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml

	# Enable the addon
	minikube -p=thesis addons enable ingress

	# Wait for the Nginx controller pods to be ready
	kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=90s

	# Now apply your ingress rules
	kubectl apply -f k8s/ingress-frontend.yaml
	kubectl apply -f k8s/ingress-backend.yaml

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
install-helm: 
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	kubectl create namespace monitoring
	helm install monitoring-stack prometheus-community/kube-prometheus-stack -n monitoring
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
	- kubectl rollout restart deployment locust-master
	- kubectl rollout restart deployment locust-worker
deploy-locust: 
	- kubectl apply -f k8s/locust/locust-worker.yaml
	- kubectl apply -f k8s/locust/locust-master.yaml
	- kubectl apply -f k8s/locust/locust-exporter.yaml
	- kubectl apply -f k8s/locust/locust-config.yaml
open-locust: 
	- kubectl port-forward svc/locust-master 8089:8089


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
