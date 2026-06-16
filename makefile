#### 1. Makefile for managing Minikube cluster and services
autoscale-prime: 
	kubectl autoscale deployment prime-service-deployment --cpu-percent=50 --min=1 --max=10
build-service: 
	docker build -t docker.io/boygioi/prime-service:latest ./services/prime-service
	docker build -t docker.io/boygioi/text-service:latest ./services/text-service
	docker build -t docker.io/boygioi/io-service:latest ./services/io-service
	docker build -t docker.io/boygioi/frontend-service:latest ./services/frontend
build-locust: 
	docker compose build locust

build-custom-load-test:
	CUSTOM_LOAD_TEST_IMAGE="$(TAG)" docker compose build custom-load-test
push-custom-load-test:
	docker push docker.io/boygioi/$(TAG)
build-push-custom-load-test: 
	CUSTOM_LOAD_TEST_IMAGE="$(TAG)" docker compose build custom-load-test
	docker push docker.io/boygioi/$(TAG)
pull-custom-load-test: 
	docker pull docker.io/boygioi/$(TAG)

build-forecasting-service: 
	docker build -t docker.io/boygioi/forecasting-service:latest ./forecasting-service
build-custom-scaler: 
	make -C ./custom-scaler/ docker-build docker-push IMG=docker.io/boygioi/custom-scaler:latest
build-vm-job:
	docker build -t docker.io/boygioi/vm-job:latest -f ./linux-script/vm-job.Dockerfile .
push-service: 
	docker push docker.io/boygioi/prime-service:latest
	docker push docker.io/boygioi/text-service:latest
	docker push docker.io/boygioi/io-service:latest
	docker push docker.io/boygioi/frontend-service:latest
push-vm-job:
	docker push docker.io/boygioi/vm-job:latest
push-forecasting-service: 
	docker push docker.io/boygioi/forecasting-service:latest

start:
	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/io-deployment.yaml
	- kubectl apply -f k8s/io-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml 
	- kubectl apply -f k8s/frontend-service.yaml

	# Wait for the Nginx controller pods to be ready
	kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=90s

	# Now apply your ingress rules
	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml
	- kubectl apply -f k8s/ingress-healthz.yaml


	#remember to change expose the ingress-nginx-controller svc. -- kubectl get svc -n ingress-nginx
deploy-service: 
	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/io-deployment.yaml
	- kubectl apply -f k8s/io-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml
	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml
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

restart-service: 
	- kubectl rollout restart deployment prime-service-deployment
	- kubectl rollout restart deployment text-service-deployment
	- kubectl rollout restart deployment io-service-deployment
	- kubectl rollout restart deployment frontend-deployment
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
	helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
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

run-custom-load-test:
	docker compose run --rm custom-load-test
ingress-request-counts:
	python3 helper/summarize_ingress_logs.py --input shares/ingress_raw.log --output shares/ingress_request_report.csv
capture-ingress-raw-logs:
	sh helper/capture_ingress_raw_logs.sh shares/ingress_raw.log


#curl -X PUT http://localhost:1208?n=5
#### 2. Makefile for managing Minikube cluster and services with cgroup adjustments
start-environment: 
	$(MAKE)	start
# 	bash ./linux-script/enforce-machine-slice-cpuset.sh
# 	bash ./linux-script/lock-cpu-frequency.sh
stop-environment: 
	minikube -p=thesis stop
	bash ./linux-script/release-cpu-frequency.sh

# scp k3s-master:~/predictive-autoscaling-k8s-test/shares/ingress_request_report.csv ~/predictive-autoscaling-k8s-test/shares/ingress_request_report.csv
# kubectl apply -f custom-scaler/config/samples/autoscaling_v1_customscaler.yaml
# kubectl scale deployment/custom-scaler-controller-manager -n custom-scaler-system --replicas=0
