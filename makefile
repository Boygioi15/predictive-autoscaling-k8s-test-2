#### 1. Makefile for managing Minikube cluster and services
REGISTRY ?= docker.io/boygioi
DEMO_APP_IMAGE ?= $(REGISTRY)/general-resource-demand-service:latest
FORECASTING_IMAGE ?= $(REGISTRY)/forecasting-service:latest
VM_JOB_IMAGE ?= $(REGISTRY)/vm-job:latest

autoscale-demo-app:
	kubectl autoscale deployment demo-app-deployment --cpu-percent=50 --min=1 --max=10
	
build-push-demo-app:
	docker buildx build --push -t $(DEMO_APP_IMAGE) ./general-resource-demand-service

################### BUILD PUSH DOCKER ###################
build-locust: 
	docker compose build locust

build-push-custom-load-generator:
	CUSTOM_LOAD_GENERATOR_IMAGE="$(TAG)" docker compose build --push custom-load-generator

build-push-forecasting-service:
	docker buildx build --push -t $(FORECASTING_IMAGE) ./forecasting-service
build-push-vm-job:
	docker buildx build --push -t $(VM_JOB_IMAGE) -f ./linux-script/vm-job.Dockerfile .

build-custom-scaler: 
	make -C ./custom-scaler/ docker-build docker-push IMG=docker.io/boygioi/custom-scaler:latest


################### Apply/ deploy in k8s ###################
deploy-demo-app: 
	- kubectl apply -f k8s/demo-app-deployment.yaml
	- kubectl apply -f k8s/demo-app-service.yaml
	- kubectl apply -f k8s/demo-app-ingress.yaml
	- kubectl apply -f k8s/ingress-healthz.yaml
deploy-forecasting-service:
	- kubectl apply -f ./k8s/forecasting-service.yaml
restart-forecasting-service:
	- kubectl apply -f k8s/forecasting-service.yaml
	- kubectl rollout restart deployment/forecasting-service-deployment
	- kubectl logs deploy/forecasting-service-deployment
deploy-custom-scaler: 
	make -C ./custom-scaler/ install
	make -C ./custom-scaler/ deploy IMG=docker.io/boygioi/custom-scaler:latest
	kubectl apply -f ~/predictive-autoscaling-k8s-test/custom-scaler/config/samples/autoscaling_v1_customscaler.yaml
	kubectl rollout restart deployment/custom-scaler-controller-manager -n custom-scaler-system

restart-demo-app: 
	- kubectl rollout restart deployment demo-app-deployment

deploy-monitor: 
	- kubectl apply -f k8s/monitor.yaml
restart-monitor: 
	- kubectl rollout restart deployment monitoring-stack-kube-prometheus-stack-grafana -n monitoring
	- kubectl rollout restart statefulset monitoring-stack-kube-prometheus-stack-kube-prom-prometheus -n monitoring
open-grafana: 
	- kubectl port-forward svc/monitoring-stack-grafana 3000:80 -n monitoring
open-prometheus: 
	- kubectl port-forward prometheus-monitoring-stack-kube-prom-prometheus-0  9090:9090 -n monitoring

run-custom-load-generator:
	CUSTOM_LOAD_GENERATOR_IMAGE="$(TAG)" docker compose run --rm custom-load-generator

install-helm-monitor: 
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	kubectl get namespace monitoring >/dev/null 2>&1 || kubectl create namespace monitoring
	helm upgrade --install monitoring-stack prometheus-community/kube-prometheus-stack \
		-n monitoring \
		--wait \
		--debug \
		--timeout 15m \
		-f k8s/monitoring-values.yaml
install-helm-ingress: 
	helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
	helm repo update
	helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
	-n ingress-nginx \
	--reuse-values \
	--set controller.extraArgs.metrics-per-host=true \
	--set controller.extraArgs.metrics-per-undefined-host=true \
	--create-namespace \
	--set controller.metrics.enabled=true \
	--set controller.metrics.serviceMonitor.enabled=true \
	--set controller.metrics.serviceMonitor.additionalLabels.release="monitoring-stack" \
	--debug
# # This ensures metrics, the ServiceMonitor for Prometheus, and stub-status are all ON
# helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
#   -n ingress-nginx \
#   --set controller.metrics.enabled=true \
#   --set controller.metrics.serviceMonitor.enabled=true \
#   --set controller.metrics.serviceMonitor.additionalLabels.release="monitoring-stack"




# configure-ingress-logging:
# 	kubectl patch configmap ingress-nginx-controller -n ingress-nginx --type merge --patch-file k8s/ingress-nginx-log-config-patch.yaml
# 	kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx
# 	kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=90s

# ingress-request-counts:
# 	python3 helper/summarize_ingress_logs.py --input shares/ingress_raw.log --output shares/ingress_request_report.csv
# capture-ingress-raw-logs:
# 	sh helper/capture_ingress_raw_logs.sh shares/ingress_raw.log

#curl -X PUT http://localhost:1208?n=5
#### 2. Makefile for managing Minikube cluster and services with cgroup adjustments
# start-environment: 
# 	$(MAKE)	start
# # 	bash ./linux-script/enforce-machine-slice-cpuset.sh
# # 	bash ./linux-script/lock-cpu-frequency.sh
# stop-environment: 
# 	minikube -p=thesis stop
# 	bash ./linux-script/release-cpu-frequency.sh

# scp k3s-master:~/predictive-autoscaling-k8s-test/shares/ingress_request_report.csv ~/predictive-autoscaling-k8s-test/shares/ingress_request_report.csv
# kubectl apply -f custom-scaler/config/samples/autoscaling_v1_customscaler.yaml
# kubectl scale deployment/custom-scaler-controller-manager -n custom-scaler-system --replicas=0
