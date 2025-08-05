# Packaging IaC Stack

The IaC is packaged and attached to each release using GitHub Actions.  Below is the manual procedure:

1. Zip the Iac with Archives
    ```bash
    zip -r ai-optimizer-iac.zip . -x "terraform*" ".terraform*" "*/terraform*" "*/.terraform*" "cfgmgt/stage/*.*"
    ```

## version.tf

The version.tf file is automatically updated during the release cycle.  
The contents should otherwise be `app_version = "0.0.0"` to indicate a non-release.