+++
title = 'Infrastructure as Code'
weight = 1
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore opentofu ollama imagelink kubeconfig
-->

The {{< full_app_ref >}} can easily be deployed in Oracle Cloud Infrastructure (**OCI**) using Infrastructure as Code (**IaC**) provided in the source [opentofu](https://github.com/oracle/ai-optimizer/tree/main/opentofu) directory.

Choose between deploying a light-weight [Virtual Machine](#virtual-machine) or robust [Oracle Kubernetes Engine (**OKE**)](#oracle-kubernetes-engine) along with the **Oracle Autonomous Database** for a fully configured {{< short_app_ref >}} environment, ready to use.  

While the **IaC** can be run from a command-line with prior experience, the steps outlined here use [Oracle Cloud Resource Manager](https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Concepts/resourcemanager.htm) to simplify the process.  To get started:

{{< imagelink url="https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/oracle/ai-optimizer/releases/latest/download/ai-optimizer-iac.zip" src="https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg" alt="Deploy to Oracle Cloud" >}}

## Virtual Machine

The Virtual Machine (VM) deployment provisions both the {{< short_app_ref >}} API Server and GUI Client together in an "All-in-One" configuration for experimentation and development.  

There will be an option to deploy on a **GPU**, which will be more expensive then a **CPU** but will, as part of the deployment, make available one local Large Language Model and one Embedding Model for use out-of-the-box. 

{{% notice style="code" title="Models Needed!" icon="traffic-light" %}}
If deploying the VM IaC on a **CPU**, you will need to [configure a model](/client/configuration/model_config) for functionality. 
{{% /notice %}}

### Configure Variables

After clicking the "Deploy to Oracle Cloud" button and authenticating to your tenancy; you will be presented with the {{< short_app_ref >}} stack information.

1. Review the Terms, tick the box to accept (if you do), and click "Next" to Configure Variables

    ![Stack Information](../images/iac_stack_information.png)

1. Change the Infrastructure to "VM"

    ![Stack - AI Optimizer](../images/iac_stack_vm_optimizer.png)

#### Access Control

Most of the other configuration options are self-explanatory, but let's highlight those important for the **Security** of your deployment.

* The {{< short_app_ref >}} is often configured with authentication details for your OCI Tenancy, Autonomous Database, and API Keys for AI Models. Since these details are accessible via the Application GUI, access _must_ be restricted to a limited set of CIDR blocks.

* The {{< short_app_ref >}} REST endpoints require API token authentication, providing some protection. However, you should still restrict access to a limited set of CIDR blocks where possible for added security.

* The **Oracle Autonomous Database** requires mTLS authentication with a wallet, providing strong initial protection. However, it is recommended to further restrict access to a limited set of CIDR blocks.

![Stack - Access Control](../images/iac_stack_access_control.png)

To restrict access, provide a comma-separated list of CIDR blocks, for example: `192.168.1.0/24,10.0.0.0/16,203.0.113.42/32`

In this example:
* `192.168.1.0/24` – Allows access from all IPs in the range 192.168.1.0 to 192.168.1.255 (a typical subnet).
* `10.0.0.0/16` – Allows access from 10.0.0.0 to 10.0.255.255 (a broader range).
* `203.0.113.42/32` – Allows access from a single public IP address only. The /32 denotes a single host.

### Review and Apply

After configuring the variables, click "Next" to review and apply the stack.

![Stack - Review and Apply](../images/iac_stack_review_apply.png)

Tick the Apply box and click "Create".

### Job Details

The next screen will show the progress of the Apply job.  Once the job has Succeeded, the {{< short_app_ref >}} has been deployed!

The Application Information tab will provide the URL's to access the {{< short_app_ref >}} GUI and API Server.  In the "All-in-One" deployment on the VM, the API Server will only become accessible after visiting the GUI at least once.

![Stack - VM Application Information](../images/iac_stack_vm_info.png)

{{% notice style="code" title="502 Bad Gateway: Communication Breakdown!" icon="fire" %}}
Although the infrastructure is deployed, the {{< short_app_ref >}} may still be initializing, which can result in a 502 Bad Gateway error when accessing the URLs. Please allow up to 10 minutes for the configuration to complete.
{{% /notice %}}

To get a better understanding of how the API Server works and to obtain the API Key for making REST calls, review the [API Server documentation](client/api_server/).

### Cleanup

To destroy the {{< short_app_ref >}} infrastructure, in **OCI** navigate to `Developer Services` -> `Stacks`.  Choose the Compartment the {{< short_app_ref >}} was deployed into and select the stack Name.  Click on the "Destroy" button.

---

## Oracle Kubernetes Engine

The Kubernetes (**K8s**) deployment provisions the {{< short_app_ref >}} in a the managed Oracle Kubernetes Engine service.  The {{< short_app_ref >}} API Server and GUI Client will be run in separate K8s Deployments for a more robust, production-ready architecture.  As part of the deployment, you can choose to deploy a GPU Worker Node where one local Large Language Model and one Embedding Model will be made available out-of-the-box.

![OCI OKE](../images/infra_oci.png)

### Configure Variables

After clicking the "Deploy to Oracle Cloud" button and authenticating to your tenancy; you will be presented with the {{< short_app_ref >}} stack information.

1. Review the Terms, tick the box to accept (if you do), and click "Next" to Configure Variables

    ![Stack Information](../images/iac_stack_information.png)

1. Change the Infrastructure to "Kubernetes"

    ![Stack - AI Optimizer](../images/iac_stack_k8s_optimizer.png)

#### Access Control

Most of the other configuration options are self-explanatory, but let's highlight those important for the **Security** of your deployment.

* The **Oracle Kubernetes Engine API Endpoint** can be made public so that you can manage your cluster resources.  If you expose the K8s API endpoint, it is _highly advised_ to restrict access to a limited set of CIDR blocks.

* The {{< short_app_ref >}} is often configured with authentication details for your OCI Tenancy, Autonomous Database, and API Keys for AI Models. Since these details are accessible via the Application GUI, access _must_ be restricted to a limited set of CIDR blocks.

* The {{< short_app_ref >}} REST endpoints require API token authentication, providing some protection. However, you should still restrict access to a limited set of CIDR blocks where possible for added security.

* The **Oracle Autonomous Database** requires mTLS authentication with a wallet, providing strong initial protection. However, it is recommended to further restrict access to a limited set of CIDR blocks.

![Stack K8s - Access Control](../images/iac_stack_k8s_access_control.png)
![Stack - Access Control](../images/iac_stack_access_control.png)

To restrict access, provide a comma-separated list of CIDR blocks, for example: `192.168.1.0/24,10.0.0.0/16,203.0.113.42/32`

In this example:
* `192.168.1.0/24` – Allows access from all IPs in the range 192.168.1.0 to 192.168.1.255 (a typical subnet).
* `10.0.0.0/16` – Allows access from 10.0.0.0 to 10.0.255.255 (a broader range).
* `203.0.113.42/32` – Allows access from a single public IP address only. The /32 denotes a single host.

### Review and Apply

After configuring the variables, click "Next" to review and apply the stack.

![Stack - Review and Apply](../images/iac_stack_review_apply.png)

Tick the Apply box and click "Create".

### Job Details

The next screen will show the progress of the Apply job.  Once the job has Succeeded, the {{< short_app_ref >}} has been deployed!

The Application Information tab will provide the URL's to access the {{< short_app_ref >}} GUI and API Server.  The command to create a `kubeconfig` file for connecting to your cluster using `kubectl` will also be provided.

![Stack - K8s Application Information](../images/iac_stack_k8s_info.png)

{{% notice style="code" title="502 Bad Gateway: Communication Breakdown!" icon="fire" %}}
Although the infrastructure is deployed, the {{< short_app_ref >}} may still be initializing, which can result in a 502 Bad Gateway error when accessing the URLs. Please allow up to 10 minutes for the configuration to complete.
{{% /notice %}}

To get a better understanding of how the API Server works and to obtain the API Key for making REST calls, review the [API Server documentation](client/api_server/).

### Cleanup

To destroy the {{< short_app_ref >}} infrastructure, in **OCI** navigate to `Developer Services` -> `Stacks`.  Choose the Compartment the {{< short_app_ref >}} was deployed into and select the stack Name.  Click on the "Destroy" button.