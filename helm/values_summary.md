## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

# --Global Configuration
global:
  api:
    # -- API Key; you must specify either apiKey or name of an existing Secret
    apiKey: ""
    # -- The Helm chart supports storing the API Key in a secret.
    # The secret needs to contain one key with its value set
    secretName: "hologram-api-keys"
    # -- Name of the key in the secret containing the API Key, overrides the default key name "apiKey"
    secretKey: ""

server:
  replicaCount: 1
  image:
    repository: localhost/ai-optimizer-server
    tag: "latest"
  imagePullPolicy: IfNotPresent
  imagePullSecrets: []
  # - name: regcred

  ingress:
    enabled: false
    className: nginx
    annotations:
      nginx.ingress.kubernetes.io/ssl-redirect: "false"
      nginx.ingress.kubernetes.io/upstream-vhost: "localhost"
    tls: []

    autoscaling:
      enabled: false
      # minReplicas: 1
      # maxReplicas: 100
      # targetCPUUtilizationPercentage: 80
      # targetMemoryUtilizationPercentage: 80

    resources: {}
      # We usually recommend not to specify default resources and to leave this as a conscious
      # choice for the user. This also increases chances charts run on environments with little
      # resources, such as Minikube. If you do want to specify resources, uncomment the following
      # lines, adjust them as necessary, and remove the curly braces after 'resources:'.
      # limits:
      #   cpu: 100m
      #   memory: 128Mi
      # requests:
      #   cpu: 100m
      #   memory: 128Mi

    serviceAccount:
      create: false

    service:
      http:
        type: "ClusterIP"

    # -- Oracle Autonomous Database Configuration
    adb:
      enabled: false
      ocid: ""
      mtlsWallet: ""
      authN:
          secretName: ""
          usernameKey: ""
          passwordKey: ""
          serviceKey: ""

    # -- Model Configuration
    models:
      openAI:
          secretName: ""
          secretKey: ""
      perplexity:
          secretName: ""
          secretKey: ""
      cohere:
          secretName: ""
          secretKey: ""
      huggingface:
          # -- e.g http://hf.hf.svc.cluster.local:8080
          urlPort: ""

    # -- Additional volumes on the output Deployment definition.
    volumes: []
    # - name: foo
    #   secret:
    #     secretName: mysecret
    #     optional: false

    # -- Additional volumeMounts on the output Deployment definition.
    volumeMounts: []
    # - name: foo
    #   mountPath: "/etc/foo"
    #   readOnly: true

# -- Client GUI configuration
client:
  replicaCount: 1
  image:
    repository: localhost/ai-optimizer-client
    tag: "latest"
  imagePullPolicy: IfNotPresent
  imagePullSecrets: []
    # - name: regcred

  ingress:
    enabled: false
    className: nginx
    annotations:
      nginx.ingress.kubernetes.io/ssl-redirect: "false"
      nginx.ingress.kubernetes.io/upstream-vhost: "localhost"
    tls: []

  autoscaling:
    enabled: false
    minReplicas: 1
    maxReplicas: 100
    targetCPUUtilizationPercentage: 80
    targetMemoryUtilizationPercentage: 80

  resources: {}
    # We usually recommend not to specify default resources and to leave this as a conscious
    # choice for the user. This also increases chances charts run on environments with little
    # resources, such as Minikube. If you do want to specify resources, uncomment the following
    # lines, adjust them as necessary, and remove the curly braces after 'resources:'.
    # limits:
    #   cpu: 100m
    #   memory: 128Mi
    # requests:
    #   cpu: 100m
    #   memory: 128Mi

  serviceAccount:
    create: false

  service:
    http:
      type: "ClusterIP"

  client:
    features:
      disableTestbed: "false"
      disableApi: "false"
      disableTools: "false"
      disableDbCfg: "false"
      disableModelCfg: "false"
      disableOciCfg: "false"
      disableSettings: "false"

  # -- Additional volumes on the output Deployment definition.
  volumes: []
  # - name: foo
  #   secret:
  #     secretName: mysecret
  #     optional: false

  # -- Additional volumeMounts on the output Deployment definition.
  volumeMounts: []
  # - name: foo
  #   mountPath: "/etc/foo"
  #   readOnly: true

# -- Ollama Installation
ollama:
  replicaCount: 1
  image:
    repository: docker.io/ollama/ollama
    tag: "latest"
  imagePullPolicy: IfNotPresent

  autoscaling:
    enabled: false
    # minReplicas: 1
    # maxReplicas: 100
    # targetCPUUtilizationPercentage: 80
    # targetMemoryUtilizationPercentage: 80

  resources: {}
    # We usually recommend not to specify default resources and to leave this as a conscious
    # choice for the user. This also increases chances charts run on environments with little
    # resources, such as Minikube. If you do want to specify resources, uncomment the following
    # lines, adjust them as necessary, and remove the curly braces after 'resources:'.
    # limits:
    #   cpu: 100m
    #   memory: 128Mi
    # requests:
    #   cpu: 100m
    #   memory: 128Mi

  tolerations: {}

  serviceAccount:
    create: false

  service:
    http:
      type: "ClusterIP"

  # -- Models to deploy.
  models: []
  # - foo
  # - bar
  
  # -- Additional volumes on the output Deployment definition.
  volumes: []
  # - name: foo
  #   secret:
  #     secretName: mysecret
  #     optional: false

  # -- Additional volumeMounts on the output Deployment definition.
  volumeMounts: []
  # - name: foo
  #   mountPath: "/etc/foo"
  #   readOnly: true