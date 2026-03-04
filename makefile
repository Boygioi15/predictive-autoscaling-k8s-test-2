start:
	minikube start --driver=hyperv

	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml

	minikube addons enable ingress

	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml

	minikube tunnel
deploy: 
	- kubectl apply -f k8s/prime-deployment.yaml
	- kubectl apply -f k8s/prime-service.yaml
	- kubectl apply -f k8s/text-deployment.yaml
	- kubectl apply -f k8s/text-service.yaml
	- kubectl apply -f k8s/frontend-deployment.yaml
	- kubectl apply -f k8s/frontend-service.yaml
	- kubectl apply -f k8s/ingress-frontend.yaml
	- kubectl apply -f k8s/ingress-backend.yaml
deploy-monitor: 
	- kubectl apply -f k8s/monitor.yaml
start-grafana: 
	- kubectl port-forward svc/monitoring-stack-grafana 3000:80 -n monitoring
start-prometheus: 
	- kubectl port-forward prometheus-monitoring-stack-kube-prom-prometheus-0  9090:9090 -n monitoring
stop:
	- kubectl delete deployment,service -l app=text-service
	- kubectl delete deployment,service -l app=prime-service
	- kubectl delete deployment,service -l app=frontend
	- kubectl delete ingress ingress-frontend
	- kubectl delete ingress ingress-backend
	minikube stop
