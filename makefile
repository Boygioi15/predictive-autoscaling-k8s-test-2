#### 1. Makefile for managing Minikube cluster and services
build-service: 
	minikube image build -t prime-service:v1 ./services/prime-service
	minikube image build -t text-service:v1 ./services/text-service
	minikube image build -t frontend:v1 ./services/frontend
build-locust: 
	minikube image build -t locust-test:v1 ./locust-test
start:
	minikube start --driver=kvm2 --container-runtime=containerd

	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml

	# Enable the addon
	minikube addons enable ingress

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
install-helm: 
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	kubectl create namespace monitoring
	helm install monitoring-stack prometheus-community/kube-prometheus-stack -n monitoring
deploy-monitor: 
	- kubectl apply -f k8s/monitor.yaml
open-grafana: 
	- kubectl port-forward svc/monitoring-stack-grafana 3000:80 -n monitoring
open-prometheus: 
	- kubectl port-forward prometheus-monitoring-stack-kube-prom-prometheus-0  9090:9090 -n monitoring
deploy-locust: 
	- kubectl apply -f k8s/locust/locust-worker.yaml
	- kubectl apply -f k8s/locust/locust-master.yaml
open-locust: 
	- kubectl port-forward svc/locust-master 8089:8089


#### 2. Makefile for managing Minikube cluster and services with cgroup adjustments
start-environment: 
	$(MAKE)	start
	bash ./linux-script/enforce-machine-slice-cpuset.sh
	bash ./linux-script/lock-cpu-frequency.sh
stop-environment: 
	minikube stop
	bash ./linux-script/release-cpu-frequency.sh
