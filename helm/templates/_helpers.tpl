{{/* 
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl. 
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "release.name" -}}
{{ .Release.Name }}
{{- end }}

{{- define "chart.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Define the ServiceName of the API Server for Client Access.
*/}}
{{- define "server.serviceName" -}}
{{ include "release.name" . }}-server-http
{{- end -}}

{{- define "server.serviceUrl" -}}
http://{{ include "server.serviceName" . }}.{{ .Release.Namespace }}.svc.cluster.local
{{- end -}}

{{/*
Define the ServiceName of the Ollama.
*/}}
{{- define "ollama.serviceName" -}}
{{ include "release.name" . }}-ollama-http
{{- end -}}

{{- define "ollama.serviceUrl" -}}
http://{{ include "ollama.serviceName" . }}.{{ .Release.Namespace }}.svc.cluster.local:11434
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
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
Create chart name and version as used by the chart label.
*/}}
{{- define "app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
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

{{/*
Create the name of the service account to use
*/}}
{{- define "app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "app.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Set the path based on baseUrlPath
*/}}
{{- define "getPath" -}}
{{- $baseUrlPath := .Values.baseUrlPath | default "" -}}
{{- if eq $baseUrlPath "" -}}
/
{{- else if not (hasPrefix "/" $baseUrlPath) -}}
{{- printf "/%s" $baseUrlPath -}}
{{- else -}}
{{- $baseUrlPath -}}
{{- end -}}
{{- end -}}