# custom-scaler

## Description
Kubernetes custom operator that periodically calls an external forecasting HTTP service, reads a sequence forecast, and converts predicted RPS into a target Deployment replica count. The operator requeues each `CustomScaler` resource based on its configured `intervalMinutes`, so every scaler can poll on its own cadence.

Sample `CustomScaler` spec:

```yaml
spec:
  url: http://forecasting-service.default.svc.cluster.local:8080/forecast
  deploymentName: prime-service-deployment
  forecastDeployment: prime-service
  intervalMinutes: 1
  safeRpsPerPod: 20
  safetyFactor: 1.10
  sparePod: 1
  minReplicas: 1
  maxReplicas: 10
```

The operator expects the forecasting service to return a JSON payload like:

```json
{
  "deployment": "prime-service",
  "step_seconds": 60,
  "predictions": [18.0, 20.0, 19.0, 21.0, 20.0]
}
```

It then applies the first scaling policy:

```text
peak_rps = max(predictions)
effective_rps = peak_rps * safety_factor
desired_replicas = ceil(effective_rps / safe_rps_per_pod)
if desired_replicas > 0:
    desired_replicas += spare_pod
desired_replicas = clamp(desired_replicas, min_replicas, max_replicas)
```

## Environment-backed defaults

The controller-manager deployment provides global defaults through environment
variables:

- `SCALER_SAFE_RPS_PER_POD`
- `SCALER_SAFETY_FACTOR`
- `SCALER_SPARE_POD`
- `SCALER_MIN_REPLICAS`
- `SCALER_MAX_REPLICAS`

Each `CustomScaler` resource can override these values in its own spec when
needed.

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
