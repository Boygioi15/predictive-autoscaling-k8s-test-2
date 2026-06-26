# custom-scaler

## Description
Kubernetes custom operator that periodically calls an external forecasting HTTP service, reads a workload forecast, and converts the forecast into a target Deployment replica count. The operator requeues each `CustomScaler` resource based on its configured `intervalMinutes`, so every scaler can poll on its own cadence.

Sample `CustomScaler` spec:

```yaml
spec:
  url: http://forecasting-service.default.svc.cluster.local:8080/forecast
  deploymentName: demo-app-deployment
  intervalMinutes: 1
  safetyFactor: 1.10
  sparePod: 1
  minReplicas: 1
  maxReplicas: 10
```

The operator expects the forecasting service to return a JSON payload like:

```json
{
  "deployment": "demo-app",
  "contract_id": "demo-linear-regression-v1",
  "step_seconds": 60,
  "predictions": [1500.0, 1525.0, 1488.0],
  "prediction_rows": [
    {
      "datetime": "2026-06-25T01:01:00Z",
      "total_requests_per_minute": 1500.0,
      "total_cpu_seconds_per_minute": 27.5,
      "total_bandwidth_bytes_per_minute": 21000000.0
    }
  ]
}
```

It then applies the current scaling policy:

```text
peak_requests = max(predictions)
peak_cpu_seconds = max(prediction_rows[*].total_cpu_seconds_per_minute)

effective_requests = peak_requests * safety_factor
effective_cpu_seconds = peak_cpu_seconds * safety_factor

request_replicas = ceil(effective_requests / requests_per_pod)
cpu_replicas = ceil(effective_cpu_seconds / cpu_seconds_per_pod)

desired_replicas = max(request_replicas, cpu_replicas)
if desired_replicas > 0:
    desired_replicas += spare_pod
desired_replicas = clamp(desired_replicas, min_replicas, max_replicas)
```

The controller then applies a separate reactive bump on top of that forecast
baseline. If the last `SCALER_REACTIVE_REQUIRED_POINTS` observed points
both satisfy:

```text
app_error_rate > SCALER_APP_ERROR_RATE_THRESHOLD
OR
ingress_p99_seconds > SCALER_INGRESS_P99_THRESHOLD_SECONDS
```

then it increases the `ReactivePressureBump` state and adds:

```text
ReactivePressureBump * SCALER_REACTIVE_REPLICA_STEP
```

extra replicas to the forecast-driven result.

## Environment-backed defaults

The controller-manager deployment provides global defaults through environment
variables:

- `SCALER_FORECAST_CONTRACT_ID`
- `SCALER_REQUESTS_PER_POD`
- `SCALER_CPU_SECONDS_PER_POD`
- `SCALER_SAFETY_FACTOR`
- `SCALER_SPARE_POD`
- `SCALER_MIN_REPLICAS`
- `SCALER_MAX_REPLICAS`
- `SCALER_APP_ERROR_RATE_THRESHOLD`
- `SCALER_INGRESS_P99_THRESHOLD_SECONDS`
- `SCALER_REACTIVE_REQUIRED_POINTS`
- `SCALER_REACTIVE_INCREASE_STEP`
- `SCALER_REACTIVE_DECREASE_STEP`
- `SCALER_REACTIVE_MAX_BUMP`
- `SCALER_REACTIVE_REPLICA_STEP`

The request contract id currently comes from the controller-manager env. The
legacy `safeRpsPerPod` field is still accepted as a per-scaler override for
request-capacity if you need a quick one-off override.

## Getting Started

### Prerequisites
- go version v1.24.6+
- docker version 17.03+.
- kubectl version v1.11.3+.
- Access to a Kubernetes v1.11.3+ cluster.

### To Deploy on the cluster
**Build and push your image to the location specified by `IMG`:**

```sh
make docker-build docker-push IMG=<some-registry>/custom-scaler:tag
```

**NOTE:** This image ought to be published in the personal registry you specified.
And it is required to have access to pull the image from the working environment.
Make sure you have the proper permission to the registry if the above commands don’t work.

**Install the CRDs into the cluster:**

```sh
make install
```

**Deploy the Manager to the cluster with the image specified by `IMG`:**

```sh
make deploy IMG=<some-registry>/custom-scaler:tag
```

> **NOTE**: If you encounter RBAC errors, you may need to grant yourself cluster-admin
privileges or be logged in as admin.

**Create instances of your solution**
You can apply the samples (examples) from the config/sample:

```sh
kubectl apply -k config/samples/
```

>**NOTE**: Ensure that the samples has default values to test it out.

### To Uninstall
**Delete the instances (CRs) from the cluster:**

```sh
kubectl delete -k config/samples/
```

**Delete the APIs(CRDs) from the cluster:**

```sh
make uninstall
```

**UnDeploy the controller from the cluster:**

```sh
make undeploy
```

## Project Distribution

Following the options to release and provide this solution to the users.

### By providing a bundle with all YAML files

1. Build the installer for the image built and published in the registry:

```sh
make build-installer IMG=<some-registry>/custom-scaler:tag
```

**NOTE:** The makefile target mentioned above generates an 'install.yaml'
file in the dist directory. This file contains all the resources built
with Kustomize, which are necessary to install this project without its
dependencies.

2. Using the installer

Users can just run 'kubectl apply -f <URL for YAML BUNDLE>' to install
the project, i.e.:

```sh
kubectl apply -f https://raw.githubusercontent.com/<org>/custom-scaler/<tag or branch>/dist/install.yaml
```

### By providing a Helm Chart

1. Build the chart using the optional helm plugin

```sh
kubebuilder edit --plugins=helm/v2-alpha
```

2. See that a chart was generated under 'dist/chart', and users
can obtain this solution from there.

**NOTE:** If you change the project, you need to update the Helm Chart
using the same command above to sync the latest changes. Furthermore,
if you create webhooks, you need to use the above command with
the '--force' flag and manually ensure that any custom configuration
previously added to 'dist/chart/values.yaml' or 'dist/chart/manager/manager.yaml'
is manually re-applied afterwards.

## Contributing
// TODO(user): Add detailed information on how you would like others to contribute to this project

**NOTE:** Run `make help` for more information on all potential `make` targets

More information can be found via the [Kubebuilder Documentation](https://book.kubebuilder.io/introduction.html)

## License

Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
