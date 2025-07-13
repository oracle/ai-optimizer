{{/* 
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
spell-checker: ignore trunc ollama
*/}}

{{/* ******************************************
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*********************************************** */}}
{{- define "global.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" | trim }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" | trim }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" | trim }}
{{- end }}
{{- end }}
{{- end }}


{{/* ******************************************
Expand the name of the chart.
*********************************************** */}}
{{- define "global.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" | trim }}
{{- end }}


{{/* ******************************************
Create chart name and version as used by the chart label.
*********************************************** */}}
{{- define "global.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" | trim }}
{{- end }}


{{/* ******************************************
Selector labels
*********************************************** */}}
{{- define "global.selectorLabels" -}}
app.kubernetes.io/name: {{ include "global.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}


{{/* ******************************************
Common labels
*********************************************** */}}
{{- define "global.labels" -}}
helm.sh/chart: {{ include "global.chart" . }}
{{ include "global.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{/* ******************************************
Validate that either global.api.apiKey or global.api.secretName is provided.
*********************************************** */}}
{{- define "global.apiKeyOrSecretName.required" -}}
  {{- $apiKey := .Values.global.api.apiKey | trim | default "" -}}
  {{- $secretName := .Values.global.api.secretName | trim | default "" -}}

  {{- if and (eq $apiKey "") (eq $secretName "") -}}
    {{- fail "You must specify either global.api.apiKey or global.api.secretName" -}}
  {{- end -}}

  {{- if and (ne $apiKey "") (ne $secretName "") -}}
    {{- fail "You cannot specify both global.api.apiKey and global.api.secretName; please choose one" -}}
  {{- end -}}
{{- end -}}

{{/* ******************************************
Define the API Key Secret with Defaults
*********************************************** */}}
{{- define "global.apiSecretName" -}}
{{- .Values.global.api.secretName | default (printf "%s-api-key" .Release.Name) -}}
{{- end }}

{{- define "global.apiSecretKey" -}}
{{- .Values.global.api.secretKey | default "apiKey" -}}
{{- end }}


{{/* ******************************************
Set the path based on baseUrlPath
*********************************************** */}}
{{- define "global.getPath" -}}
  {{- $baseUrlPath := .Values.global.baseUrlPath | default "" -}}
  {{- if eq $baseUrlPath "" -}}
    /
  {{- else if not (hasPrefix "/" $baseUrlPath) -}}
    {{- printf "/%s" $baseUrlPath -}}
  {{- else -}}
    {{- $baseUrlPath -}}
  {{- end -}}
{{- end -}}


{{/* ******************************************
Define the serviceName and serviceUrl of the API Server for Client Access.
*********************************************** */}}
{{- define "server.serviceName" -}}
{{ include "global.fullname" . }}-server-8000
{{- end -}}

{{- define "server.serviceUrl" -}}
http://{{ include "server.serviceName" . }}.{{ .Release.Namespace }}.svc.cluster.local
{{- end -}}


{{/* ******************************************
Define serviceName and serviceUrl of the Ollama Server for API Server Access.
*********************************************** */}}
{{- define "ollama.serviceName" -}}
{{ .Release.Name }}-ollama-11434
{{- end -}}

{{- define "ollama.serviceUrl" -}}
http://{{ include "ollama.serviceName" . }}.{{ .Release.Namespace }}.svc.cluster.local:11434
{{- end -}}


{{/* ******************************************
Database Secret Name
*********************************************** */}}
{{- define "server.databaseSecret" -}}
{{- $authN := .Values.server.database.authN | default dict }}
{{- $secretName := $authN.secretName | default "" }}
{{- if $secretName -}}
  {{- $secretName -}}
{{- else -}}
  {{- printf "%s-db-authn" (include "release.name" .) -}}
{{- end -}}
{{- end }}


{{/* ******************************************
Database Privileged Secret Name
*********************************************** */}}
{{- define "server.databasePrivSecret" -}}
{{- $authN := .Values.server.database.privAuthN | default dict }}
{{- $secretName := $authN.secretName | default "" }}
{{- if $secretName -}}
  {{- $secretName -}}
{{- else -}}
  {{- printf "%s-db-priv-authn" (include "release.name" .) -}}
{{- end -}}
{{- end }}


{{/* ******************************************
Environment to include Database Authentication
*********************************************** */}}
{{- define "server.database.authN" -}}
- name: DB_USERNAME
  valueFrom:
    secretKeyRef:
        name: {{ include "server.databaseSecret" . }}
        key: {{ default "username" .Values.server.database.authN.usernameKey }}
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
        name: {{ include "server.databaseSecret" . }}
        key: {{ default "password" .Values.server.database.authN.passwordKey }}
- name: DB_DSN
  valueFrom:
    secretKeyRef:
        name: {{ include "server.databaseSecret" . }}
        key: {{ default "service" .Values.server.database.authN.serviceKey }}
{{- end }}


{{/* ******************************************
Create the pull model list for Ollama
*********************************************** */}}
{{- define "ollama.modelPullList" -}}
  {{- if and .Values.ollama.models.enabled .Values.ollama.models.modelPullList }}
    {{- join " " .Values.ollama.models.modelPullList -}}
  {{- else }}
    {{- "" -}}
  {{- end }}
{{- end -}}

{{/* ******************************************
Password Generator for Databases
*********************************************** */}}
{{- define "server.randomPassword" -}}
  {{- $minLen := 12 -}}
  {{- $maxLen := 30 -}}
  {{- $one := int 1 -}}
  {{- $two := int 2 -}}

  {{- /* Random length between min and max */ -}}
  {{- $range := int (add (sub $maxLen $minLen) 1) -}}
  {{- $randOffset := int (randInt 0 $range) -}}
  {{- $length := add $minLen $randOffset -}}

  {{- /* Required characters */ -}}
  {{- $upper := randAlphaNum $one | upper -}}
  {{- $lower := randAlphaNum $one | lower -}}
  {{- $digit := randNumeric $one -}}
  {{- $start := randAlpha $one | lower -}}

  {{- /* Special character, one of "-" or "_" */ -}}
  {{- $specialChars := list "-" "_" -}}
  {{- $specialIndex := int (randInt 0 $two) -}}
  {{- $special := index $specialChars $specialIndex -}}

  {{- /* Remaining characters to reach desired length */ -}}
  {{- $restLength := int (sub $length 5) -}}
  {{- $rest := randAlphaNum $restLength -}}

  {{- /* Final password */ -}}
  {{- $password := printf "%s%s%s%s%s%s" $start $special $upper $lower $digit $rest -}}
  {{- $password -}}
{{- end }}