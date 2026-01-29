#!/bin/bash
# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

## https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/gettingmetadata.htm
oke_init_url='http://169.254.169.254/opc/v2/instance/metadata/oke_init_script'
curl --fail -H "Authorization: Bearer Oracle" -L0 "${oke_init_url}" | base64 --decode >/var/run/oke-init.sh

# detect architecture
arch=$(uname -m)
if [ "$arch" = "aarch64" ]; then
    binary_url="https://github.com/oracle-devrel/oke-credential-provider-for-ocir/releases/latest/download/oke-credential-provider-for-ocir-linux-arm64"
else
    binary_url="https://github.com/oracle-devrel/oke-credential-provider-for-ocir/releases/latest/download/oke-credential-provider-for-ocir-linux-amd64"
fi

# download OCIR Access binaries on the worker node
wget "$binary_url" -O /usr/local/bin/credential-provider-oke
wget https://github.com/oracle-devrel/oke-credential-provider-for-ocir/releases/latest/download/credential-provider-config.yaml -P /etc/kubernetes/
# add permission to execute
sudo chmod 755 /usr/local/bin/credential-provider-oke
# configure kubelet with image credential provider
bash /var/run/oke-init.sh --kubelet-extra-args "--image-credential-provider-bin-dir=/usr/local/bin/ --image-credential-provider-config=/etc/kubernetes/credential-provider-config.yaml"