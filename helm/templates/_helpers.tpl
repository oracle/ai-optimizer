{{/* 
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
spell-checker: ignore ollama
*/}}

{{/*
Return the Helm release name.
*/}}
{{- define "release.name" -}}
  {{- .Release.Name | trim }}
{{- end }}

{{/*
Return the Chart Name
*/}}
{{- define "chart.name" -}}
  {{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" | trim }}
{{- end }}

{{/*
Return the Chart Name with Version
*/}}
{{- define "app.chart" -}}
  {{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" | trim }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncates at 63 characters because some Kubernetes name fields are limited by the DNS naming spec.
If .Values.fullnameOverride is set, it takes precedence.
If the release name contains the chart name, we use it directly.
*/}}
{{- define "app.fullname" -}}
  {{- if .Values.fullnameOverride }}
    {{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
    {{- $name := default .Chart.Name .Values.nameOverride }}
    {{- if contains $name .Release.Name }}
      {{- .Release.Name | trunc 63 | trimSuffix "-" }}
    {{- else }}
      {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
    {{- end }}
  {{- end }}
{{- end }}


{{/*
Common labels
*/}}
{{- define "app.labels" -}}
helm.sh/chart: {{ include "app.chart" . }}
{{ include "app.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "chart.name" . }}
app.kubernetes.io/instance: {{ include "release.name" . }}
{{- end }}

{{- /*
Validate that either global.api.apiKey or global.api.secretName is provided.
*/ -}}
{{- define "apiKeyOrSecretName.required" -}}
  {{- $apiKey := .Values.global.api.apiKey | trim | default "" -}}
  {{- $secretName := .Values.global.api.secretName | trim | default "" -}}

  {{- if and (eq $apiKey "") (eq $secretName "") -}}
    {{- fail "You must specify either global.api.apiKey or global.api.secretName" -}}
  {{- end -}}

  {{- if and (ne $apiKey "") (ne $secretName "") -}}
    {{- fail "You cannot specify both global.api.apiKey and global.api.secretName; please choose one" -}}
  {{- end -}}
{{- end -}}

{{/*
Define the API Key Secret with Defaults
*/}}
{{- define "app.apiSecretName" -}}
{{- .Values.global.api.secretName | default (printf "%s-api-key" (include "release.name" .)) -}}
{{- end }}

{{- define "app.apiSecretKey" -}}
{{- .Values.global.api.secretKey | default "apiKey" -}}
{{- end }}

{{/*
Set the path based on baseUrlPath
*/}}
{{- define "getPath" -}}
  {{- $baseUrlPath := .Values.global.baseUrlPath | default "" -}}
  {{- if eq $baseUrlPath "" -}}
    /
  {{- else if not (hasPrefix "/" $baseUrlPath) -}}
    {{- printf "/%s" $baseUrlPath -}}
  {{- else -}}
    {{- $baseUrlPath -}}
  {{- end -}}
{{- end -}}

{{/*
Define the serviceName and serviceUrl of the API Server for Client Access.
*/}}
{{- define "server.serviceName" -}}
{{ include "release.name" . }}-server-http
{{- end -}}

{{- define "server.serviceUrl" -}}
http://{{ include "server.serviceName" . }}.{{ .Release.Namespace }}.svc.cluster.local
{{- end -}}

{{/*
Define serviceName and serviceUrl of the Ollama Server for API Server Access.
*/}}
{{- define "ollama.serviceName" -}}
{{ include "release.name" . }}-ollama-http
{{- end -}}

{{- define "ollama.serviceUrl" -}}
http://{{ include "ollama.serviceName" . }}.{{ .Release.Namespace }}.svc.cluster.local:11434
{{- end -}}
