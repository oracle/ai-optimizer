{{/*
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
spell-checker: ignore trunc ollama
*/}}

{{/* ******************************************
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*********************************************** */}}
{{- define "ai-optimizer.fullname" -}}
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
{{- define "ai-optimizer.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" | trim }}
{{- end }}


{{/* ******************************************
Create chart name and version as used by the chart label.
*********************************************** */}}
{{- define "ai-optimizer.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" | trim }}
{{- end }}


{{/* ******************************************
Selector labels
*********************************************** */}}
{{- define "ai-optimizer.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ai-optimizer.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}


{{/* ******************************************
Common labels
*********************************************** */}}
{{- define "ai-optimizer.labels" -}}
helm.sh/chart: {{ include "ai-optimizer.chart" . }}
{{ include "ai-optimizer.selectorLabels" . }}
app.kubernetes.io/part-of: ai-optimizer
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{/* ******************************************
Resolved image string for any component.

Pass: dict "image" .Values.<component>.image "global" .Values.global

Returns "<registry>/<repository>:<tag>". When .global.imageRegistry is
non-empty it wins over .image.registry — this is the chart-wide registry
override (set --set global.imageRegistry=mirror.acme.local once and every
component pulls from the mirror).

If `.image.repository` is already host-qualified (its first slash-segment
contains a `.` or `:`, or is exactly `localhost`, e.g.
`iad.ocir.io/tenant/proj/ai-optimizer-server`, `localhost:5000/foo`, or
`localhost/ai-optimizer-server`), it's used verbatim and both
`.image.registry` and `.global.imageRegistry` are ignored — preventing
nonsensical refs like `localhost/iad.ocir.io/...` or
`localhost/localhost/...` when an operator passes a fully-qualified
repository alongside the chart's default registry. Operators who want
the global mirror to override must use unqualified repositories.
*********************************************** */}}
{{- define "ai-optimizer.image" -}}
{{- $repo := .image.repository -}}
{{/* Tag fallback: use the explicit `image.tag` when set; otherwise the
     caller-supplied `appVersion` (typically `.Chart.AppVersion`). Restores
     the pre-helper behavior of `image.tag | default .Chart.AppVersion`
     so existing values overrides that set tag="" don't render as
     `repo:` (trailing colon). */}}
{{- $tag := .image.tag -}}
{{- if not $tag -}}
{{- $tag = .appVersion | default "" -}}
{{- end -}}
{{- $tag = $tag | toString -}}
{{- if or (eq $tag "") (eq $tag "latest") (eq $tag "head") (eq $tag "canary") -}}
{{- fail (printf "image tag for repository %q must be pinned; use a fixed tag or leave server/client tags empty to default to Chart.appVersion" $repo) -}}
{{- end -}}
{{- $first := index (splitList "/" $repo) 0 -}}
{{- $repoHasHost := or (contains "." $first) (contains ":" $first) (eq $first "localhost") -}}
{{- if $repoHasHost -}}
{{- printf "%s:%s" $repo $tag -}}
{{- else -}}
{{- $reg := default .image.registry .global.imageRegistry | default "" -}}
{{- if $reg -}}
{{- printf "%s/%s:%s" $reg $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}
{{- end }}


{{/* ******************************************
Render an `imagePullSecrets:` block when the merged list of
component-level + global pull secrets is non-empty. Renders nothing
when both lists are empty.

Pass: dict "local" .Values.<component>.imagePullSecrets "global" .Values.global.imagePullSecrets

Entries may be plain strings ("mirror-creds") or maps ({name: mirror-creds});
both are normalized to the pod-spec map form.
*********************************************** */}}
{{- define "ai-optimizer.imagePullSecrets" -}}
{{- $merged := concat (default (list) .global) (default (list) .local) | uniq -}}
{{- with $merged }}
imagePullSecrets:
{{- range . }}
{{- if kindIs "map" . }}
- {{ toYaml . | nindent 2 | trim }}
{{- else }}
- name: {{ . }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}


{{/* ******************************************
Shell library for chart-managed Job containers.

Emits a POSIX `wait_until` function: runs the given command repeatedly
until it exits 0 or `max` attempts elapse. On exhaustion it returns
non-zero (so callers using `set -e` abort, and the Job's backoffLimit
takes over). Stdout/stderr from the probed command are not redirected,
so callers control verbosity via the command itself (e.g., `curl -s`).

Usage in a script:
  {{`{{ include "ai-optimizer.shellWaitFunc" . | nindent 10 }}`}}
  wait_until "<label>" <max> <sleep_s> <cmd> [args...]
*********************************************** */}}
{{- define "ai-optimizer.shellWaitFunc" -}}
wait_until() {
  label="$1"; max="$2"; s="$3"; shift 3
  i=1
  while [ "$i" -le "$max" ]; do
    if "$@"; then return 0; fi
    echo "Waiting for $label ($i/$max)"
    sleep "$s"
    i=$((i + 1))
  done
  echo "ERROR: $label not ready after $max attempts" >&2
  return 1
}
{{- end }}


{{/* ******************************************
Validate that either global.api.apiKey or global.api.secretName is provided.
*********************************************** */}}
{{- define "ai-optimizer.apiKeyOrSecretName.required" -}}
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
{{- define "ai-optimizer.apiSecretName" -}}
{{- .Values.global.api.secretName | default (printf "%s-api-key" (include "ai-optimizer.fullname" .)) -}}
{{- end }}

{{- define "ai-optimizer.apiSecretKey" -}}
{{- .Values.global.api.secretKey | default "apiKey" -}}
{{- end }}


{{/* ******************************************
Validate that either client.cookieSecret or client.cookieSecretName is provided.
The cookie secret must be stable and operator-provided so Streamlit state remains
consistent across replicas. Same contract as global.api.apiKey.
*********************************************** */}}
{{- define "ai-optimizer.client.cookieKeyOrSecretName.required" -}}
  {{- $cookieSecret := .Values.client.cookieSecret | trim | default "" -}}
  {{- $secretName := .Values.client.cookieSecretName | trim | default "" -}}

  {{- if and (eq $cookieSecret "") (eq $secretName "") -}}
    {{- fail "You must specify either client.cookieSecret or client.cookieSecretName" -}}
  {{- end -}}

  {{- if and (ne $cookieSecret "") (ne $secretName "") -}}
    {{- fail "You cannot specify both client.cookieSecret and client.cookieSecretName; please choose one" -}}
  {{- end -}}
{{- end -}}

{{/* ******************************************
Define the Client Cookie Secret name/key with defaults.
Trim first so whitespace-only values are treated as unset (consistent with the
validator above). Without the trim, a value like "   " would be truthy and skip
the `default` fallback, producing invalid manifests (metadata.name: "   ") or
letting a whitespace cookieSecret clobber an operator-owned external Secret.
*********************************************** */}}
{{- define "ai-optimizer.client.cookieSecretName" -}}
{{- $explicit := .Values.client.cookieSecretName | trim -}}
{{- if $explicit -}}{{ $explicit }}{{- else -}}{{ printf "%s-client-cookie" (include "ai-optimizer.fullname" .) }}{{- end -}}
{{- end }}

{{- define "ai-optimizer.client.cookieSecretKey" -}}
{{- $explicit := .Values.client.cookieSecretKey | trim -}}
{{- if $explicit -}}{{ $explicit }}{{- else -}}cookieSecret{{- end -}}
{{- end }}

{{/* ******************************************
Validate the three mutually-exclusive client password paths. At most one of
client.password, client.passwordSecretName, or client.passwordAutoGenerate
may be active. Combinations are ambiguous (which Secret does the deployment
bind, who owns the lifecycle); fail loudly rather than apply silent precedence.
*********************************************** */}}
{{- define "ai-optimizer.client.passwordBothSet.fail" -}}
  {{- $inline := .Values.client.password | trim | default "" -}}
  {{- $byo := .Values.client.passwordSecretName | trim | default "" -}}
  {{- $auto := .Values.client.passwordAutoGenerate -}}
  {{- $count := 0 -}}
  {{- if ne $inline "" -}}{{- $count = add $count 1 -}}{{- end -}}
  {{- if ne $byo "" -}}{{- $count = add $count 1 -}}{{- end -}}
  {{- if $auto -}}{{- $count = add $count 1 -}}{{- end -}}
  {{- if gt $count 1 -}}
    {{- fail "client.password, client.passwordSecretName, and client.passwordAutoGenerate are mutually exclusive; set at most one" -}}
  {{- end -}}
{{- end -}}

{{/* ******************************************
Returns "true" when the additional client UI access check is active. Off
unless one of client.password, client.passwordSecretName, or
client.passwordAutoGenerate is set. When off, AIO_CLIENT_PASSWORD is not
rendered into the client pod env.
*********************************************** */}}
{{- define "ai-optimizer.client.passwordGate.enabled" -}}
{{- if or (.Values.client.password | trim) (.Values.client.passwordSecretName | trim) .Values.client.passwordAutoGenerate -}}true{{- end -}}
{{- end -}}

{{/* ******************************************
Define the Client Password Secret name/key with defaults. Same trimming
rationale as the cookie helpers: whitespace-only values are treated as unset.
*********************************************** */}}
{{- define "ai-optimizer.client.passwordSecretName" -}}
{{- $explicit := .Values.client.passwordSecretName | trim -}}
{{- if $explicit -}}{{ $explicit }}{{- else -}}{{ printf "%s-client-password" (include "ai-optimizer.fullname" .) }}{{- end -}}
{{- end }}

{{- define "ai-optimizer.client.passwordSecretKey" -}}
{{- $explicit := .Values.client.passwordSecretKey | trim -}}
{{- if $explicit -}}{{ $explicit }}{{- else -}}password{{- end -}}
{{- end }}

{{/* ******************************************
Checksum used to roll the client Deployment when the cookie-signing secret
changes. Two branches:

  * Inline path (.Values.client.cookieSecret set): hash the rendered cookie-secret.yaml.
    The hash changes whenever the chart-managed Secret's value changes.

  * External path (.Values.client.cookieSecretName set): use `lookup` to read
    the operator-owned Secret from the cluster and hash its current data. On
    `helm upgrade` after the operator rotates the Secret in place, the content
    changes → hash changes → pods roll. During `helm template` / `--dry-run` /
    first install, `lookup` returns empty; we fall back to a name-keyed
    sentinel so the annotation is still stable and distinct per configuration.

Rotation workflow for the external path: operator rotates the Secret, then
runs `helm upgrade` (or equivalent CD step). Fully automated rotation on
Secret-change requires a reloader controller and is out of scope for this chart.
*********************************************** */}}
{{- define "ai-optimizer.client.cookieSecretChecksum" -}}
{{- if .Values.client.cookieSecret | trim -}}
{{- include (print $.Template.BasePath "/client/cookie-secret.yaml") . | sha256sum -}}
{{- else -}}
  {{- $name := include "ai-optimizer.client.cookieSecretName" . -}}
  {{- $key := include "ai-optimizer.client.cookieSecretKey" . -}}
  {{- $found := lookup "v1" "Secret" .Release.Namespace $name -}}
  {{- if and $found $found.data (hasKey $found.data $key) -}}
{{- printf "live:%s:%s" $name (index $found.data $key) | sha256sum -}}
  {{- else -}}
{{- printf "unresolved:%s:%s" $name $key | sha256sum -}}
  {{- end -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Checksum used to roll the client Deployment when the shared password Secret
changes. Mirrors client.cookieSecretChecksum:

  * Inline path (client.password set): hash the rendered password-secret.yaml.
    The cookie checksum already hashes the same file, so when BOTH cookie and
    password are inline a value change on either rotates the pod — accepted
    over-rotation; under-rotation is the bug we are preventing.

  * Lookup path (client.passwordSecretName set OR passwordAutoGenerate true):
    `lookup` the Secret at the resolved name and hash its current data. BYO
    is operator-owned; auto-generate is the default-name Secret created by
    password-secret.yaml. Both bind the same Secret in the Deployment. During
    `helm template` / `--dry-run` / first install, `lookup` returns empty; we
    fall back to a name-keyed sentinel so the annotation stays stable and
    distinct per configuration.

  * Gate disabled (none set): constant sentinel.
*********************************************** */}}
{{- define "ai-optimizer.client.passwordSecretChecksum" -}}
{{- if .Values.client.password | trim -}}
{{- include (print $.Template.BasePath "/client/password-secret.yaml") . | sha256sum -}}
{{- else if or (.Values.client.passwordSecretName | trim) .Values.client.passwordAutoGenerate -}}
  {{- $name := include "ai-optimizer.client.passwordSecretName" . -}}
  {{- $key := include "ai-optimizer.client.passwordSecretKey" . -}}
  {{- $found := lookup "v1" "Secret" .Release.Namespace $name -}}
  {{- if and $found $found.data (hasKey $found.data $key) -}}
{{- printf "live:%s:%s" $name (index $found.data $key) | sha256sum -}}
  {{- else -}}
{{- printf "unresolved:%s:%s" $name $key | sha256sum -}}
  {{- end -}}
{{- else -}}
{{- printf "gate-disabled" | sha256sum -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Set the path based on baseUrlPath
Always returns a path with leading and trailing slashes for proper concatenation.
*********************************************** */}}
{{- define "ai-optimizer.getPath" -}}
  {{- $baseUrlPath := .Values.global.baseUrlPath | default "" -}}
  {{- if eq $baseUrlPath "" -}}
    /
  {{- else -}}
    {{- $path := $baseUrlPath -}}
    {{- if not (hasPrefix "/" $path) -}}
      {{- $path = printf "/%s" $path -}}
    {{- end -}}
    {{- if not (hasSuffix "/" $path) -}}
      {{- $path = printf "%s/" $path -}}
    {{- end -}}
    {{- $path -}}
  {{- end -}}
{{- end -}}


{{/* ******************************************
Define the serviceName and serviceUrl of the API Server for Client Access.
*********************************************** */}}
{{- define "ai-optimizer.server.serviceName" -}}
{{ include "ai-optimizer.fullname" . }}-server-http
{{- end -}}

{{- define "ai-optimizer.server.serviceUrl" -}}
http://{{ include "ai-optimizer.server.serviceName" . }}.{{ .Release.Namespace }}.svc
{{- end -}}


{{/* ******************************************
Define serviceName and serviceUrl of the Ollama Server for API Server Access.
*********************************************** */}}
{{- define "ai-optimizer.ollama.serviceName" -}}
{{ include "ai-optimizer.fullname" . }}-ollama-11434
{{- end -}}

{{- define "ai-optimizer.ollama.serviceUrl" -}}
http://{{ include "ai-optimizer.ollama.serviceName" . }}.{{ .Release.Namespace }}.svc:11434
{{- end -}}


{{/* ******************************************
Env Secret Name Helpers
Returns either the user-provided secretName or a generated name.
*********************************************** */}}
{{- define "ai-optimizer.server.envSecretName" -}}
{{- $envSecret := .Values.server.envSecret | default dict -}}
{{- $envSecret.secretName | default (printf "%s-server-env" (include "ai-optimizer.fullname" .)) -}}
{{- end -}}

{{- define "ai-optimizer.server.envSecretKey" -}}
{{- $envSecret := .Values.server.envSecret | default dict -}}
{{- $envSecret.secretKey | default "server.env" -}}
{{- end -}}

{{- define "ai-optimizer.client.envSecretName" -}}
{{- $envSecret := .Values.client.envSecret | default dict -}}
{{- $envSecret.secretName | default (printf "%s-client-env" (include "ai-optimizer.fullname" .)) -}}
{{- end -}}

{{- define "ai-optimizer.client.envSecretKey" -}}
{{- $envSecret := .Values.client.envSecret | default dict -}}
{{- $envSecret.secretKey | default "client.env" -}}
{{- end -}}

{{/* ******************************************
Checksums used to roll pods when the rendered env Secret content
changes. The entrypoint loads .env.{AIO_ENV} once at startup, so when a
helm upgrade flips a value that lands in the env Secret (maxClients,
SSL, OKE, Ollama URL, server URL, operator overrides via
envSecret.content), the pod template must change too — otherwise running
pods keep stale config.

Inline path hashes the rendered env-secret template. External path
(`envSecret.secretName` set) uses `lookup` to read the operator-owned
Secret's live content; falls back to a name-keyed sentinel during
`helm template`/`--dry-run`/first install so the annotation is still
stable and distinct per configuration.
*********************************************** */}}
{{- define "ai-optimizer.server.envSecretChecksum" -}}
{{- $envSecret := .Values.server.envSecret | default dict -}}
{{- $secretName := $envSecret.secretName | default "" | trim -}}
{{- if eq $secretName "" -}}
{{- include (print $.Template.BasePath "/server/env-secret.yaml") . | sha256sum -}}
{{- else -}}
  {{- $key := include "ai-optimizer.server.envSecretKey" . -}}
  {{- $found := lookup "v1" "Secret" .Release.Namespace $secretName -}}
  {{- if and $found $found.data (hasKey $found.data $key) -}}
{{- printf "live:%s:%s" $secretName (index $found.data $key) | sha256sum -}}
  {{- else -}}
{{- printf "unresolved:%s:%s" $secretName $key | sha256sum -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{- define "ai-optimizer.client.envSecretChecksum" -}}
{{- $envSecret := .Values.client.envSecret | default dict -}}
{{- $secretName := $envSecret.secretName | default "" | trim -}}
{{- if eq $secretName "" -}}
{{- include (print $.Template.BasePath "/client/env-secret.yaml") . | sha256sum -}}
{{- else -}}
  {{- $key := include "ai-optimizer.client.envSecretKey" . -}}
  {{- $found := lookup "v1" "Secret" .Release.Namespace $secretName -}}
  {{- if and $found $found.data (hasKey $found.data $key) -}}
{{- printf "live:%s:%s" $secretName (index $found.data $key) | sha256sum -}}
  {{- else -}}
{{- printf "unresolved:%s:%s" $secretName $key | sha256sum -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/* ******************************************
Compose the server's `.env.{AIO_ENV}` content as a dotenv string
(`KEY=value` per line, terminated with `\n`). Chart-derived
`AIO_*` settings flow through the
Secret-mounted file rather than as pod env entries. Operator-supplied
`server.envSecret.content` overrides chart defaults via mergeOverwrite.
*********************************************** */}}
{{- define "ai-optimizer.server.envContent" -}}
{{- $out := dict -}}
{{- $_ := set $out "AIO_SERVER_URL_PREFIX" (include "ai-optimizer.getPath" . | trimSuffix "/") -}}
{{- $_ = set $out "AIO_MAX_CLIENTS" (.Values.server.maxClients | toString) -}}
{{- with .Values.server.ssl -}}
{{- if .enabled -}}
{{- $_ = set $out "AIO_SERVER_SSL" "true" -}}
{{- if .certFile -}}{{- $_ = set $out "AIO_SERVER_SSL_CERT_FILE" .certFile -}}{{- end -}}
{{- if .keyFile -}}{{- $_ = set $out "AIO_SERVER_SSL_KEY_FILE" .keyFile -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- with .Values.server.ociConfig -}}
{{- if (default false .oke) -}}
{{- $_ = set $out "AIO_OCI_CLI_REGION" .region -}}
{{- $_ = set $out "AIO_OCI_CLI_AUTH" "oke_workload_identity" -}}
{{- end -}}
{{- end -}}
{{- if .Values.ollama.enabled -}}
{{- $_ = set $out "AIO_ON_PREM_OLLAMA_URL" (include "ai-optimizer.ollama.serviceUrl" .) -}}
{{- end -}}
{{- with .Values.server.envSecret -}}{{- with .content -}}
{{- $_ = mergeOverwrite $out . -}}
{{- end -}}{{- end -}}
{{- $lines := list -}}
{{- range $k, $v := $out -}}
{{- $lines = append $lines (printf "%s=%s" $k ($v | toString)) -}}
{{- end -}}
{{- join "\n" $lines -}}
{{- end -}}

{{/* ******************************************
Compose the client's `.env.{AIO_ENV}` content as a dotenv string.
Same contract as server.envContent.
*********************************************** */}}
{{- define "ai-optimizer.client.envContent" -}}
{{- $out := dict -}}
{{- $_ := set $out "AIO_SERVER_URL" (include "ai-optimizer.server.serviceUrl" .) -}}
{{- $_ = set $out "AIO_SERVER_PORT" (.Values.server.service.port | default 8000 | toString) -}}
{{- with .Values.client.ssl -}}
{{- if .enabled -}}
{{- $_ = set $out "AIO_CLIENT_SSL" "true" -}}
{{- if .certFile -}}{{- $_ = set $out "AIO_CLIENT_SSL_CERT_FILE" .certFile -}}{{- end -}}
{{- if .keyFile -}}{{- $_ = set $out "AIO_CLIENT_SSL_KEY_FILE" .keyFile -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- with .Values.client.envSecret -}}{{- with .content -}}
{{- $_ = mergeOverwrite $out . -}}
{{- end -}}{{- end -}}
{{- $lines := list -}}
{{- range $k, $v := $out -}}
{{- $lines = append $lines (printf "%s=%s" $k ($v | toString)) -}}
{{- end -}}
{{- join "\n" $lines -}}
{{- end -}}


{{/* ******************************************
Database Secret Name
*********************************************** */}}
{{- define "ai-optimizer.server.databaseSecret" -}}
{{- $authn := .Values.server.database.authn | default dict }}
{{- $secretName := $authn.secretName | default "" }}
{{- if $secretName -}}
  {{- $secretName -}}
{{- else -}}
  {{- printf "%s-db-authn" (include "ai-optimizer.fullname" .) -}}
{{- end -}}
{{- end }}


{{/* ******************************************
Database Privileged Secret Name
*********************************************** */}}
{{- define "ai-optimizer.server.databasePrivSecret" -}}
{{- $privAuthn := .Values.server.database.privAuthn | default dict }}
{{- $secretName := $privAuthn.secretName | default "" }}
{{- if $secretName -}}
  {{- $secretName -}}
{{- else -}}
  {{- printf "%s-db-priv-authn" (include "ai-optimizer.fullname" .) -}}
{{- end -}}
{{- end }}


{{/* ******************************************
Environment to include Database Authentication
*********************************************** */}}
{{- define "ai-optimizer.server.database.authn" -}}
- name: AIO_DB_USERNAME
  valueFrom:
    secretKeyRef:
        name: {{ include "ai-optimizer.server.databaseSecret" . }}
        key: {{ default "username" .Values.server.database.authn.usernameKey }}
- name: AIO_DB_PASSWORD
  valueFrom:
    secretKeyRef:
        name: {{ include "ai-optimizer.server.databaseSecret" . }}
        key: {{ default "password" .Values.server.database.authn.passwordKey }}
- name: AIO_DB_DSN
  valueFrom:
    secretKeyRef:
        name: {{ include "ai-optimizer.server.databaseSecret" . }}
        key: {{ default "service" .Values.server.database.authn.serviceKey }}
{{- end }}


{{/* ******************************************
Create the pull model list for Ollama
*********************************************** */}}
{{- define "ai-optimizer.ollama.modelPullList" -}}
  {{- if and .Values.ollama.models.enabled .Values.ollama.models.modelPullList }}
    {{- join " " .Values.ollama.models.modelPullList -}}
  {{- else }}
    {{- "" -}}
  {{- end }}
{{- end -}}

{{/* ******************************************
Validate that server.database.adb.serviceName is provided when database type is ADB-S
and no external authn secret overrides the default.
*********************************************** */}}
{{- define "ai-optimizer.server.database.validateADBSType" -}}
  {{- if eq (include "ai-optimizer.server.database.isADBS" .) "true" -}}
    {{- $adb := .Values.server.database.adb | default dict -}}
    {{- $serviceName := $adb.serviceName | default "" -}}
    {{- if eq ($serviceName | trim) "" -}}
      {{- fail "server.database.type is ADB-S: must provide server.database.adb.serviceName (TNS alias from wallet tnsnames.ora, e.g., mydb_low)" -}}
    {{- end -}}
  {{- end -}}
{{- end -}}

{{/* ******************************************
Validate that server.database.other fields are provided when database type is OTHER.
Requires either 'dsn' OR all of (host, port, serviceName).
*********************************************** */}}
{{- define "ai-optimizer.server.database.validateOtherType" -}}
  {{- if .Values.server.database -}}
    {{- $dbType := .Values.server.database.type | default "" -}}

    {{- if eq $dbType "OTHER" -}}
      {{- $dsn := .Values.server.database.other.dsn -}}
      {{- $host := .Values.server.database.other.host -}}
      {{- $port := .Values.server.database.other.port -}}
      {{- $serviceName := .Values.server.database.other.serviceName -}}

      {{- /* Check if dsn is provided and not empty */ -}}
      {{- $hasDsn := false -}}
      {{- if $dsn -}}
        {{- if and (kindIs "string" $dsn) (ne ($dsn | trim) "") -}}
          {{- $hasDsn = true -}}
        {{- end -}}
      {{- end -}}

      {{- /* Check if individual fields are provided */ -}}
      {{- $hasHost := false -}}
      {{- if $host -}}
        {{- if or (not (kindIs "string" $host)) (ne ($host | trim) "") -}}
          {{- $hasHost = true -}}
        {{- end -}}
      {{- end -}}

      {{- $hasPort := false -}}
      {{- if $port -}}
        {{- if or (not (kindIs "string" $port)) (ne ($port | trim) "") -}}
          {{- $hasPort = true -}}
        {{- end -}}
      {{- end -}}

      {{- $hasServiceName := false -}}
      {{- if $serviceName -}}
        {{- if or (not (kindIs "string" $serviceName)) (ne ($serviceName | trim) "") -}}
          {{- $hasServiceName = true -}}
        {{- end -}}
      {{- end -}}

      {{- /* Validate: must have either dsn OR all three individual fields */ -}}
      {{- if not $hasDsn -}}
        {{- if not (and $hasHost $hasPort $hasServiceName) -}}
          {{- fail "server.database.type is OTHER: must provide either 'dsn' OR all of (host, port, serviceName)" -}}
        {{- end -}}
      {{- end -}}

      {{- /* OTHER mode owns the user lifecycle but the chart doesn't run a
             new database — the application user must already exist on the
             external DB or be creatable by the chart's init Job.
             Require explicit operator intent so a chart-generated random
             password isn't paired with a user that was never created:
               * authn.secretName set → operator brings their own user/Secret,
                 init Job is skipped.
               * privAuthn.secretName set → chart provisions the AI_OPTIMIZER
                 user via the init Job using the operator's privileged creds.
             Empty for both means the chart would render a Secret with
             random credentials that the external DB cannot authenticate. */ -}}
      {{- $authnSecret := include "ai-optimizer.server.database.explicitAuthnName" . -}}
      {{- $privAuthSecret := include "ai-optimizer.server.database.explicitPrivAuthnName" . -}}
      {{- if and (eq $authnSecret "") (eq $privAuthSecret "") -}}
        {{- fail "server.database.type=OTHER requires either server.database.authn.secretName (a pre-created Secret with valid external-DB credentials) or server.database.privAuthn.secretName (a Secret with privileged credentials so the chart can provision the application user). Without one of these, the chart would generate random credentials that the external database cannot authenticate." -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}


{{/* ******************************************
DB Initialization Job gating: decide whether the init Job + ConfigMap
render. Returns "true" when init should run, empty otherwise. For
chart-managed databases (SIDB-FREE / ADB-FREE / ADB-S) the existing
truthy `privAuthN` check is the gate; for OTHER mode we additionally
require `privAuthn.secretName` so a BYO-user install (authn.secretName
provided, no priv creds) does not trigger a doomed init attempt.
*********************************************** */}}
{{- define "ai-optimizer.server.database.shouldRunInit" -}}
{{- $db := .Values.server.database | default dict -}}
{{- $type := $db.type | default "" -}}
{{- if and $db $type $db.privAuthn -}}
  {{- if eq (include "ai-optimizer.server.database.isOther" .) "true" -}}
    {{- if ne (include "ai-optimizer.server.database.explicitPrivAuthnName" .) "" -}}true{{- end -}}
  {{- else -}}
true
  {{- end -}}
{{- end -}}
{{- end -}}

{{/* ******************************************
Validate that if server.ociConfig.configMapName is specified,
then none of the other OCI config values (tenancy, user, fingerprint, region) should be provided.
*********************************************** */}}
{{- define "ai-optimizer.server.ociConfig.validate" -}}
  {{- if .Values.server.ociConfig -}}
    {{- $configMapName := .Values.server.ociConfig.configMapName | trim | default "" -}}
    {{- $tenancy := .Values.server.ociConfig.tenancy | trim | default "" -}}
    {{- $user := .Values.server.ociConfig.user | trim | default "" -}}
    {{- $fingerprint := .Values.server.ociConfig.fingerprint | trim | default "" -}}
    {{- $region := .Values.server.ociConfig.region | trim | default "" -}}

    {{- /* If configMapName is provided, ensure no other config values are provided */ -}}
    {{- if ne $configMapName "" -}}
      {{- if or (ne $tenancy "") (ne $user "") (ne $fingerprint "") (ne $region "") -}}
        {{- fail "server.ociConfig.configMapName is specified: you cannot also provide tenancy, user, fingerprint, or region. Either provide configMapName to reference an existing ConfigMap, OR provide the config values to create a new ConfigMap." -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}


{{/* ******************************************
ADB-S Secret Name Helpers
These helpers return the secret names for ADB-S wallet/tns-admin,
supporting either existing secrets or auto-generated ones.
*********************************************** */}}
{{- define "ai-optimizer.server.database.useExistingAdbSecrets" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- default false $adb.useExisting -}}
{{- end -}}

{{- define "ai-optimizer.server.database.adbTnsAdminSecret" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- $tnsAdmin := $adb.tnsAdminSecretName | default "" -}}
{{- if ne $tnsAdmin "" -}}
  {{- $tnsAdmin -}}
{{- else -}}
  {{- printf "%s-adb-tns-admin-%d" (include "ai-optimizer.fullname" .) .Release.Revision -}}
{{- end -}}
{{- end -}}

{{- define "ai-optimizer.server.database.adbWalletPassSecret" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- $walletPass := $adb.walletPassSecretName | default "" -}}
{{- if ne $walletPass "" -}}
  {{- $walletPass -}}
{{- else -}}
  {{- printf "%s-adb-wallet-pass-%d" (include "ai-optimizer.fullname" .) .Release.Revision -}}
{{- end -}}
{{- end -}}

{{- define "ai-optimizer.server.database.adbWalletPassSecretKey" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- $walletPassKey := $adb.walletPassSecretKey | default "" -}}
{{- if ne $walletPassKey "" -}}
  {{- $walletPassKey -}}
{{- else -}}
  {{- include "ai-optimizer.server.database.adbWalletPassSecret" . -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Database Type Helpers
These helpers provide consistent database type checking across templates.
*********************************************** */}}
{{- define "ai-optimizer.server.database.type" -}}
{{- if .Values.server.database -}}
  {{- .Values.server.database.type -}}
{{- end -}}
{{- end -}}

{{- define "ai-optimizer.server.database.isSIDB" -}}
{{- eq (include "ai-optimizer.server.database.type" .) "SIDB-FREE" -}}
{{- end -}}

{{- define "ai-optimizer.server.database.isADBFree" -}}
{{- eq (include "ai-optimizer.server.database.type" .) "ADB-FREE" -}}
{{- end -}}

{{- define "ai-optimizer.server.database.isADBS" -}}
{{- eq (include "ai-optimizer.server.database.type" .) "ADB-S" -}}
{{- end -}}

{{- define "ai-optimizer.server.database.isOther" -}}
{{- eq (include "ai-optimizer.server.database.type" .) "OTHER" -}}
{{- end -}}

{{- define "ai-optimizer.server.database.isADB" -}}
{{- or (eq (include "ai-optimizer.server.database.type" .) "ADB-S") (eq (include "ai-optimizer.server.database.type" .) "ADB-FREE") -}}
{{- end -}}

{{- define "ai-optimizer.server.database.isContainerDB" -}}
{{- or (eq (include "ai-optimizer.server.database.type" .) "SIDB-FREE") (eq (include "ai-optimizer.server.database.type" .) "ADB-FREE") -}}
{{- end -}}

{{- define "ai-optimizer.server.database.needsPrivAuth" -}}
{{- or (eq (include "ai-optimizer.server.database.isADB" .) "true") (eq (include "ai-optimizer.server.database.isOther" .) "true") -}}
{{- end -}}

{{/* ******************************************
Database Service Name Helper
Returns the short database type prefix (sidb or adb) for service naming.
*********************************************** */}}
{{- define "ai-optimizer.server.database.dbName" -}}
{{- $dbType := include "ai-optimizer.server.database.type" . -}}
{{- if $dbType -}}
  {{- lower (split "-" $dbType)._0 -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Database Service host:port for SIDB/ADB-FREE in-cluster Services.
Used both as the Service resource name and embedded in the connection
service key of the auth/priv-auth Secrets. Centralized so the resource
name and the consumer-side reference stay in lock-step.
*********************************************** */}}
{{- define "ai-optimizer.server.database.serviceName" -}}
{{- printf "%s-%s-1521" (include "ai-optimizer.fullname" .) (include "ai-optimizer.server.database.dbName" .) -}}
{{- end -}}


{{/* ******************************************
Resource name of the AutonomousDatabase CR (ADB-S).
*********************************************** */}}
{{- define "ai-optimizer.server.database.adbResourceName" -}}
{{- printf "%s-adb-s" (include "ai-optimizer.fullname" .) -}}
{{- end -}}


{{/* ******************************************
Connection-string value for the configured database type. Shared by the
authN and priv-authN Secret renderers so the SIDB/ADB-FREE host:port,
the ADB-S TNS alias, and the OTHER DSN/host:port formats stay in lock-step.
*********************************************** */}}
{{- define "ai-optimizer.server.database.connectionString" -}}
{{- if or (eq (include "ai-optimizer.server.database.isSIDB" .) "true") (eq (include "ai-optimizer.server.database.isADBFree" .) "true") -}}
{{- printf "%s:1521/FREEPDB1" (include "ai-optimizer.server.database.serviceName" .) -}}
{{- else if eq (include "ai-optimizer.server.database.isADBS" .) "true" -}}
{{- .Values.server.database.adb.serviceName -}}
{{- else if eq (include "ai-optimizer.server.database.isOther" .) "true" -}}
{{- $dsn := .Values.server.database.other.dsn | default "" | trim -}}
{{- if ne $dsn "" -}}
{{- $dsn -}}
{{- else -}}
{{- printf "%s:%v/%s" .Values.server.database.other.host .Values.server.database.other.port .Values.server.database.other.serviceName -}}
{{- end -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Operator-pinned auth/priv-auth Secret names. Empty when the operator
left the corresponding `secretName` blank (chart owns the default name);
non-empty when the operator pinned an externally managed Secret. Centralised
so the `toString | trim` normalisation can't drift across the templates
and helpers that gate on the explicit-name signal.
*********************************************** */}}
{{- define "ai-optimizer.server.database.explicitAuthnName" -}}
{{- (dig "authn" "secretName" "" (.Values.server.database | default dict)) | toString | trim -}}
{{- end -}}

{{- define "ai-optimizer.server.database.explicitPrivAuthnName" -}}
{{- (dig "privAuthn" "secretName" "" (.Values.server.database | default dict)) | toString | trim -}}
{{- end -}}


{{/* ******************************************
Default name of the chart-managed OCI config ConfigMap.
Used when server.ociConfig.configMapName is not overridden.
*********************************************** */}}
{{- define "ai-optimizer.server.ociConfigMapName" -}}
{{- .Values.server.ociConfig.configMapName | default (printf "%s-oci-config" (include "ai-optimizer.fullname" .)) -}}
{{- end -}}


{{/* ******************************************
Password Generator for Databases
*********************************************** */}}
{{- define "ai-optimizer.server.randomPassword" -}}
  {{- $minLen := 12 -}}
  {{- $maxLen := 30 -}}
  {{- $one := int 1 -}}
  {{- $two := int 2 -}}

  {{- /* Random length between min and max */ -}}
  {{- $range := int (add (sub $maxLen $minLen) 1) -}}
  {{- $randOffset := int (randInt 0 $range) -}}
  {{- $length := add $minLen $randOffset -}}

  {{- /* Required characters. randAlpha (NOT randAlphaNum) is required
         for the upper/lower slots: randAlphaNum can return a digit, and
         `| upper` / `| lower` are no-ops on digits, so the random remainder
         might leave the password with no uppercase letter at all — failing
         downstream validators (e.g., SigNoz root-user provisioning). */ -}}
  {{- $upper := randAlpha $one | upper -}}
  {{- $lower := randAlpha $one | lower -}}
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


{{/* ******************************************
Format server.otel.resourceAttributes (map) into the comma-separated
k=v form required by OTEL_RESOURCE_ATTRIBUTES. Caller has rebound `.`
to the map. Sorted for deterministic rendering across overlay merges.

Values are RFC 3986 percent-encoded before joining: the Python OTel
detector splits on "," before URL-decoding, so a literal comma (or
"=", whitespace, etc.) inside a raw value would be parsed as an
attribute boundary and silently truncate the value. urlquery uses
HTML-form escaping ("+" for space); the Python SDK's unquote() does
NOT decode "+" back to space, so convert "+" to "%20" to keep the
round trip lossless.

Keys are intentionally NOT encoded — OTel resource attribute keys
forbid commas, equals, and whitespace by spec, and encoding them
would mask user error rather than surface it.
*********************************************** */}}
{{- define "ai-optimizer.server.otel.resourceAttributes" -}}
  {{- $pairs := list -}}
  {{- range $k, $v := . -}}
    {{- $encoded := $v | toString | urlquery | replace "+" "%20" -}}
    {{- $pairs = append $pairs (printf "%s=%s" $k $encoded) -}}
  {{- end -}}
  {{- join "," (sortAlpha $pairs) -}}
{{- end -}}


{{/* ******************************************
Validate server.otel.* — fail fast on every config shape the application
would accept and silently produce zero telemetry from. An observability
feature that quietly does nothing is the worst kind of failure.

The rules below mirror the application's own exporter-selection and
log-export gating; comments next to each check describe the condition
each check handles.
*********************************************** */}}
{{- define "ai-optimizer.server.otel.validate" -}}
  {{- $otel := .Values.server.otel | default dict -}}
  {{- if $otel.enabled -}}

    {{- $supportedTracesExporters := list "otlp" "console" "none" -}}
    {{- $supportedLogsExporters := list "otlp" "none" -}}
    {{- $allowedProtocols := list "grpc" "http/protobuf" -}}
    {{- /* SigNoz subchart, when enabled, contributes per-signal endpoint
           defaults via OTEL_EXPORTER_OTLP_{TRACES,LOGS}_ENDPOINT — accept
           those as satisfying the corresponding endpoint requirements so
           operators don't have to hand-type the in-cluster collector URL.
           Each helper returns "" when the subchart is disabled OR when
           the collector port for the resolved protocol is disabled
           (`signoz.otelCollector.ports.<proto>.enabled=false`). */ -}}
    {{- $signozEnabled := ne (include "ai-optimizer.signoz.baseUrl" .) "" -}}
    {{- $signozTracesEp := include "ai-optimizer.server.otel.defaultTracesEndpoint" . -}}
    {{- $signozLogsEp := include "ai-optimizer.server.otel.defaultLogsEndpoint" . -}}

    {{- /* Parse tracesExporter strictly: every non-empty token must be one
           of the supported sentinels. Failing per-token (rather than only
           when the whole list reduces to empty) catches typos that mix
           with valid tokens, e.g. "otlp,consol" — the application's
           supported-set intersection silently drops "consol" and the
           operator would never learn about it. "none" is the OTel opt-out
           sentinel and is accepted here.
           Trim before defaulting: a whitespace-only override (e.g. from a
           templated overlay that produced spaces) should collapse to the
           same "otlp" default the empty case yields, matching what the
           deployment renderer does. */ -}}
    {{- $rawExporter := $otel.tracesExporter | default "" | trim | default "otlp" -}}
    {{- $supported := list -}}
    {{- range (splitList "," $rawExporter) -}}
      {{- $tok := . | trim -}}
      {{- if eq $tok "" -}}
        {{- /* skip empty / whitespace-only tokens */ -}}
      {{- else if has $tok $supportedTracesExporters -}}
        {{- $supported = append $supported $tok -}}
      {{- else -}}
        {{- fail (printf "ai-optimizer.server.otel.tracesExporter contains unsupported token %q. Supported tokens: \"otlp\", \"console\", \"none\". The application would silently drop this token at runtime." $tok) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Edge case: input was entirely empty / whitespace-only tokens
           (e.g. ",,, "). Per-token loop above accepts each as a skip,
           leaving $supported empty. */ -}}
    {{- if eq (len $supported) 0 -}}
      {{- fail (printf "ai-optimizer.server.otel.tracesExporter=%q has no supported entries (use \"otlp\", \"console\", \"none\", or a comma-separated mix). The application would silently produce no telemetry." (trim $rawExporter)) -}}
    {{- end -}}

    {{- /* "none" is the documented opt-out sentinel and must be the ONLY
           token. The application's exporter-set intersection silently
           drops "none" when mixed with "otlp" or "console", so a list
           like "none,otlp" still ships traces — defeating the operator's
           intent. Reject mixed lists rather than silently honoring (or
           silently ignoring) half of the user's input. */ -}}
    {{- if and (has "none" $supported) (gt (len ($supported | uniq)) 1) -}}
      {{- fail "ai-optimizer.server.otel.tracesExporter: \"none\" is the opt-out sentinel and must be the only token. The application's exporter intersection silently drops \"none\" when mixed with other tokens; use \"none\" alone to disable, or list only \"otlp\"/\"console\"." -}}
    {{- end -}}

    {{- /* OTLP traces require a generic or traces-specific endpoint;
           logsEndpoint does NOT activate traces in the app. */ -}}
    {{- $endpoint := $otel.endpoint | default "" | trim -}}
    {{- $tracesEp := $otel.tracesEndpoint | default "" | trim -}}
    {{- $haveTracesEndpoint := or (ne $endpoint "") (ne $tracesEp "") (ne $signozTracesEp "") -}}
    {{- if and (has "otlp" $supported) (not $haveTracesEndpoint) -}}
      {{- /* Distinguish the disabled-port case so the operator gets an
             actionable message rather than the generic "no endpoint". */ -}}
      {{- if and $signozEnabled (eq $endpoint "") (eq $tracesEp "") -}}
        {{- fail "ai-optimizer.server.otel: tracesExporter includes \"otlp\" and signoz.enabled=true, but the SigNoz collector port for the resolved traces protocol is disabled. Re-enable signoz.otelCollector.ports.otlp.enabled (or otlp-http.enabled if using http/protobuf), switch protocols, or set server.otel.endpoint / tracesEndpoint explicitly." -}}
      {{- else -}}
        {{- fail "ai-optimizer.server.otel: tracesExporter includes \"otlp\" but no endpoint is configured. Set server.otel.endpoint or server.otel.tracesEndpoint, enable signoz.enabled to use the in-chart collector, or set tracesExporter=\"console\" for local-only debugging." -}}
      {{- end -}}
    {{- end -}}

    {{- /* Validate OTLP protocol fields. The app lowercases but does NOT
           trim the protocol env vars, then treats any value other than
           the literal "grpc" as the HTTP exporter — so "grpc " (trailing
           whitespace) silently routes a gRPC collector via HTTP/protobuf
           and telemetry disappears. Validate strictly against the two
           values the Python OTel SDK actually supports; comparison is
           trim+case-insensitive (matches the app's lower()), rendered
           value is trimmed only — case is preserved for the operator
           and the app's own .lower() handles it from there. */ -}}
    {{- range $field, $val := dict "protocol" $otel.protocol "tracesProtocol" $otel.tracesProtocol "logsProtocol" $otel.logsProtocol -}}
      {{- $v := $val | default "" | toString | trim | lower -}}
      {{- if and (ne $v "") (not (has $v $allowedProtocols)) -}}
        {{- fail (printf "ai-optimizer.server.otel.%s=%q is not a supported OTLP protocol. Use \"grpc\" (port 4317) or \"http/protobuf\" (port 4318); empty falls back to the SDK default of grpc." $field (toString $val)) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Parse logsExporter once up-front so the explicit "none" opt-out
           can short-circuit every downstream logs check. The values.yaml
           comment promises that logsExporter=none suppresses log export
           while leaving tracing intact; the validator must defer to the
           application's opt-out branch rather than insisting on a log path. */ -}}
    {{- $logsEp := $otel.logsEndpoint | default "" | trim -}}
    {{- /* Parse logsExporter strictly. Mirrors the tracesExporter strict
           parser above so a typo like "otlp,consol" surfaces here instead
           of being silently dropped at runtime. The application's log
           exporter supports only "otlp" and "none" — "console" is a valid
           OTel spec value but not implemented for logs by this app, so
           accepting it would mislead operators expecting console output. */ -}}
    {{- $rawLogsExporter := $otel.logsExporter | default "" | trim -}}
    {{- $hasOtlpLogs := false -}}
    {{- $hasNoneLogs := false -}}
    {{- range (splitList "," $rawLogsExporter) -}}
      {{- $tok := lower (trim .) -}}
      {{- if eq $tok "" -}}
        {{- /* skip empty / whitespace-only tokens */ -}}
      {{- else if eq $tok "otlp" -}}
        {{- $hasOtlpLogs = true -}}
      {{- else if eq $tok "none" -}}
        {{- $hasNoneLogs = true -}}
      {{- else -}}
        {{- fail (printf "ai-optimizer.server.otel.logsExporter contains unsupported token %q. This application's log exporter supports only \"otlp\" or \"none\"." $tok) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Same opt-out rule as tracesExporter: "none" must be alone. For
           logs the app DOES honor mixed-"none" at runtime, but a chart
           that accepts "otlp,none" while the sibling tracesExporter
           rejects it is more confusing than one consistent rule.
           Operators learn one thing: "none" stands alone, on either field. */ -}}
    {{- if and $hasNoneLogs $hasOtlpLogs -}}
      {{- fail "ai-optimizer.server.otel.logsExporter: \"none\" is the opt-out sentinel and must be the only token. Use \"none\" alone to suppress log export, or \"otlp\" alone to ship logs." -}}
    {{- end -}}

    {{- /* logsEndpoint without OTLP in traces is wasted configuration: the
           application activates log export only when OTLP traces attach.
           Skipped when the user has explicitly opted out via "none" — the
           wasted-config concern is moot because the app ignores the endpoint. */ -}}
    {{- if and (ne $logsEp "") (not (has "otlp" $supported)) (not $hasNoneLogs) -}}
      {{- fail "ai-optimizer.server.otel.logsEndpoint is set but tracesExporter does not include \"otlp\"; the application activates log export only when OTLP traces are also active. Add \"otlp\" to tracesExporter, set logsExporter=\"none\" to acknowledge the opt-out, or remove logsEndpoint." -}}
    {{- end -}}

    {{- /* logsEnabled gates the application's log-export path. Three
           independent preconditions must hold or log export silently skips
           at runtime:
             a) OTLP traces must attach (log export piggybacks on it).
             b) The log exporter reads OTEL_EXPORTER_OTLP_LOGS_ENDPOINT,
                falling back to the generic OTEL_EXPORTER_OTLP_ENDPOINT;
                tracesEndpoint alone is invisible to it.
             c) OTEL_LOGS_EXPORTER (if set) must contain "otlp" — the app
                returns early on "none" or any list lacking otlp.
           When logsExporter=none the user has explicitly opted out and
           none of (a)–(c) apply: AIO_OTEL_LOGS_ENABLED still renders, but
           the app returns from the log-init path without needing any of them. */ -}}
    {{- if and $otel.logsEnabled (not $hasNoneLogs) -}}
      {{- if not (has "otlp" $supported) -}}
        {{- fail "ai-optimizer.server.otel.logsEnabled is true but tracesExporter does not include \"otlp\"; the application gates log export on OTLP traces being active. Either include \"otlp\" in tracesExporter (and set an endpoint), set logsExporter=\"none\" to opt out of log export, or disable logsEnabled." -}}
      {{- end -}}
      {{- if and (eq $endpoint "") (eq $logsEp "") (eq $signozLogsEp "") -}}
        {{- if and $signozEnabled -}}
          {{- fail "ai-optimizer.server.otel.logsEnabled is true and signoz.enabled=true, but the SigNoz collector port for the resolved logs protocol is disabled. Re-enable signoz.otelCollector.ports.otlp.enabled (or otlp-http.enabled if using http/protobuf), switch protocols, set server.otel.endpoint / logsEndpoint explicitly, set logsExporter=\"none\" to opt out, or disable logsEnabled." -}}
        {{- else -}}
          {{- fail "ai-optimizer.server.otel.logsEnabled is true but no log endpoint is reachable. Set server.otel.endpoint (generic, used by both signals) or server.otel.logsEndpoint, enable signoz.enabled to use the in-chart collector, set logsExporter=\"none\" to opt out, or disable logsEnabled. server.otel.tracesEndpoint alone activates only traces; the application's log exporter does not read it." -}}
        {{- end -}}
      {{- end -}}
      {{- if and (ne $rawLogsExporter "") (not $hasOtlpLogs) -}}
        {{- fail (printf "ai-optimizer.server.otel.logsEnabled is true but logsExporter=%q would silently drop logs at runtime. Use \"otlp\" to ship logs, \"none\" to explicitly suppress them, drop the value to take the default, or disable logsEnabled." $rawLogsExporter) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Plaintext headers vs Secret-sourced headers are mutually exclusive. */ -}}
    {{- $headers := $otel.headers | default "" | trim -}}
    {{- $headersSecret := $otel.headersSecret | default dict -}}
    {{- $headersSecretName := $headersSecret.name | default "" | trim -}}
    {{- if and (ne $headers "") (ne $headersSecretName "") -}}
      {{- fail "ai-optimizer.server.otel: cannot set both `headers` (plaintext) and `headersSecret.name`. Choose one." -}}
    {{- end -}}

  {{- end -}}
{{- end -}}


{{/* ******************************************
SigNoz subchart name helpers. Returns empty when signoz.enabled is false;
callers must gate on that.

`signoz.releaseFullname` mirrors the upstream SigNoz chart's `signoz.fullname`
helper, but is deliberately renamed to avoid colliding with that subchart
template — Helm's named-template namespace is global, and a parent-defined
`signoz.fullname` shadows the subchart's, leading to empty resource names
in subchart-rendered manifests when called from subchart context.

Coupling note: the rendered names also mirror the upstream
`otelCollector.fullname` shape (`<signoz.fullname>-<otelCollector.name>`).
Helm has no cross-chart helper imports, so a future SigNoz rename of
`otelCollector` would break the auto-default URL. Chart.yaml pins the
SigNoz subchart version exactly.
*********************************************** */}}
{{- define "ai-optimizer.signoz.releaseFullname" -}}
{{- $signoz := .Values.signoz | default dict -}}
{{- if $signoz.enabled -}}
{{- $override := $signoz.fullnameOverride | default "" | trim -}}
{{- $name := default "signoz" ($signoz.nameOverride | default "" | trim) -}}
{{- if ne $override "" -}}
{{- $override | trunc 63 | trimSuffix "-" -}}
{{- else if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- /* Namespace where the SigNoz subchart deploys ClickHouse and the
       operator. Mirrors the subchart's `clickhouse.namespace` helper:
       falls back to the release namespace when unset. Lifecycle hooks
       must use this rather than `.Release.Namespace` because users may
       deploy ClickHouse to a separate namespace via the documented
       `signoz.clickhouse.namespace` override. */ -}}
{{- define "ai-optimizer.signoz.clickhouseNamespace" -}}
{{- $clickhouse := dig "clickhouse" (dict) (.Values.signoz | default dict) -}}
{{- $ns := dig "namespace" "" $clickhouse | trim -}}
{{- default .Release.Namespace $ns -}}
{{- end -}}

{{- /* Resolved ClickHouseInstallation name from the SigNoz ClickHouse
       dependency. Mirrors the upstream clickhouse.fullname helper in the
       pinned SigNoz chart so lifecycle hooks can target the operator CR.
       Caller is responsible for gating on `.Values.signoz.enabled`. */ -}}
{{- define "ai-optimizer.signoz.clickhouseFullname" -}}
{{- $clickhouse := dig "clickhouse" (dict) (.Values.signoz | default dict) -}}
{{- $override := dig "fullnameOverride" "" $clickhouse | trim -}}
{{- $nameOverride := dig "nameOverride" "" $clickhouse | trim -}}
{{- $name := default "clickhouse" $nameOverride -}}
{{- if ne $override "" -}}
{{- $override | trunc 63 | trimSuffix "-" -}}
{{- else if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- /* Schemeful base URL of the in-cluster collector, no port. Returns "" when
       signoz.enabled is false. Used both as a "is the auto-default available?"
       sentinel in validation and as the building block for the per-signal
       endpoint helpers below.

       Form is `<svc>.<ns>.svc` rather than `<svc>.<ns>.svc.cluster.local`
       — pods receive a search domain that expands `.svc` to the cluster's
       configured DNS suffix automatically, so this works on any cluster
       (including those with non-default cluster domains) without a
       chart-side `clusterDomain` knob. */ -}}
{{- define "ai-optimizer.signoz.baseUrl" -}}
{{- $base := include "ai-optimizer.signoz.releaseFullname" . -}}
{{- if ne $base "" -}}
{{- $collectorName := default "otel-collector" (dig "otelCollector" "name" "" (.Values.signoz | default dict)) -}}
{{- $svc := printf "%s-%s" $base $collectorName | trunc 63 | trimSuffix "-" -}}
{{- printf "http://%s.%s.svc" $svc .Release.Namespace -}}
{{- end -}}
{{- end -}}


{{- /* Resolved name of the Secret holding the SigNoz admin credentials.
       Mirrors `global.apiSecretName` / `client.cookieSecretName`: callers
       use this rather than re-applying `default "signoz-authn"` everywhere
       (chart's authn-secret.yaml + the setup Job's volume mount). */ -}}
{{- define "ai-optimizer.signoz.authnSecretName" -}}
{{- .Values.signoz.auth.secretName | default "signoz-authn" -}}
{{- end -}}


{{- /* Whether SigNoz auto-provisions an admin from SIGNOZ_USER_ROOT_*.
       The subchart's renderEnv accepts env-map entries in scalar form
       (`KEY: "v"`) AND object form (`KEY: {value: "v"}`), and emits the
       same `value: "v"` envVar for both. Callers must accept both shapes
       — a `dig | toString` on the object form yields `map[value:true]`
       and false-negatives the predicate. valueFrom-resolved entries are
       treated as unset (a runtime-resolved boolean toggle is unsupported;
       operators set this knob directly). Returns "true" or "". */ -}}
{{- define "ai-optimizer.signoz.rootProvisioningEnabled" -}}
{{- $raw := dig "signoz" "env" "SIGNOZ_USER_ROOT_ENABLED" "" (.Values.signoz | default dict) -}}
{{- $value := "" -}}
{{- if kindIs "map" $raw -}}
{{- $value = dig "value" "" $raw -}}
{{- else -}}
{{- $value = $raw -}}
{{- end -}}
{{- if eq ($value | toString) "true" -}}true{{- end -}}
{{- end -}}


{{- /* Configured SigNoz frontend service port (default 8080). Hardcoding
       would break operators who pass through `signoz.signoz.service.port`. */ -}}
{{- define "ai-optimizer.signoz.frontendPort" -}}
{{- dig "signoz" "service" "port" 8080 (.Values.signoz | default dict) -}}
{{- end -}}


{{- /* Schemeful URL of the in-cluster SigNoz frontend (the dashboards/rules
       API the setup Job talks to), with port. Mirrors `signoz.baseUrl` but
       targets the frontend service rather than the otel-collector service.
       Returns "" when signoz.enabled is false so callers can gate. */ -}}
{{- define "ai-optimizer.signoz.frontendUrl" -}}
{{- $base := include "ai-optimizer.signoz.releaseFullname" . -}}
{{- if ne $base "" -}}
{{- printf "http://%s.%s.svc:%v" $base .Release.Namespace (include "ai-optimizer.signoz.frontendPort" .) -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
SigNoz collector port resolvers. Default to the upstream chart's defaults
(4317 gRPC / 4318 HTTP). Return "" when the port is disabled in subchart
values (`...ports.<key>.enabled=false`) so callers can detect-and-fail
rather than silently wiring an endpoint pointing at an absent port.
*********************************************** */}}
{{- /* The truthy check on the resolved port block mirrors the SigNoz
       subchart's own portsConfig: `{{- if $port.enabled }}…`. That treats
       false, null, and a missing key all as "skip the port". An operator
       can therefore disable the port via `--set …enabled=false`,
       `--set …enabled=null`, or by nulling the whole port block; in all
       three cases the Service omits the port and our helper must return
       "" so the validator catches the mismatch instead of silently
       wiring to a non-existent port. */ -}}
{{- define "ai-optimizer.signoz.collectorGrpcPort" -}}
{{- $otlp := dig "otelCollector" "ports" "otlp" (dict) (.Values.signoz | default dict) -}}
{{- if and $otlp $otlp.enabled -}}
{{- default 4317 $otlp.servicePort -}}
{{- end -}}
{{- end -}}

{{- define "ai-optimizer.signoz.collectorHttpPort" -}}
{{- $otlp := dig "otelCollector" "ports" "otlp-http" (dict) (.Values.signoz | default dict) -}}
{{- if and $otlp $otlp.enabled -}}
{{- default 4318 $otlp.servicePort -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Per-signal OTLP endpoint defaults when SigNoz is enabled and the operator
did not set the corresponding endpoint explicitly. Per-signal (rather
than a generic `OTEL_EXPORTER_OTLP_ENDPOINT`) is required: the application
falls back to the generic endpoint with each signal's own protocol
default, so a generic endpoint pinned to one protocol's port silently
breaks the other signal when the two protocols differ — e.g.
tracesProtocol=http/protobuf and logsProtocol unset routes logs to the
HTTP port over gRPC.

Plaintext gRPC vs HTTP/protobuf is intentional — the SigNoz subchart
doesn't terminate TLS on its OTLP ports, matching the Compose stack.
Operators putting SigNoz behind a TLS-terminating proxy must override
server.otel.endpoint (or the per-signal endpoints) explicitly.

The signal protocol is resolved with explicit trim-then-fallback rather
than chained `default`. Helm's `default` only fires on its empty-set
(empty string, nil, 0, empty list/map); a whitespace string like "   "
is truthy for `default` but is treated as unset by the env renderer
(which trims). Without trim-before-fallback, a whitespace tracesProtocol
+ generic protocol=http/protobuf would silently render a gRPC auto
endpoint while the app sends HTTP.
*********************************************** */}}
{{- define "ai-optimizer.server.otel.resolvedSignalProtocol" -}}
{{- /* Caller passes {signalProto, genericProto}. Returns the trimmed
       lowercased protocol the SDK will use for that signal. */ -}}
{{- $signal := trim (default "" .signalProto | toString) -}}
{{- $generic := trim (default "" .genericProto | toString) -}}
{{- if ne $signal "" -}}{{ lower $signal }}{{- else -}}{{ lower $generic }}{{- end -}}
{{- end -}}

{{- define "ai-optimizer.server.otel.signalSuffix" -}}
{{- /* Caller passes {proto, signal, grpcPort, httpPort}; returns the port
       (and signal path for HTTP) to append to the schemeful base URL,
       or "" when the port for the resolved protocol is unavailable
       (subchart's port .enabled=false → port helper returns "").

       gRPC OTLP addresses services by name (no URL path) → ":<grpcPort>".
       HTTP/protobuf signal-specific endpoints are used AS-IS by the SDK
       (no per-signal path auto-append, unlike the generic OTLP endpoint),
       so the suffix MUST include /v1/<signal> or POSTs land on `/` and
       the collector 404s. */ -}}
{{- if eq (.proto | toString) "http/protobuf" -}}
{{- if ne (.httpPort | toString) "" -}}{{- printf ":%v/v1/%s" .httpPort .signal -}}{{- end -}}
{{- else -}}
{{- if ne (.grpcPort | toString) "" -}}{{- printf ":%v" .grpcPort -}}{{- end -}}
{{- end -}}
{{- end -}}

{{- /* Per-signal default endpoints. Return "" when:
       - signoz.enabled is false (no auto-default available), OR
       - the SigNoz collector port for the resolved protocol is disabled.
       NEVER fail: callers (validator/deployment/NOTES) decide whether an
       empty result is an error based on whether OTLP is actually used
       for that signal. Failing here would abort renders that don't
       depend on the auto-default at all (e.g., tracesExporter=console,
       or explicit server.otel.endpoint). */ -}}
{{- define "ai-optimizer.server.otel.defaultTracesEndpoint" -}}
{{- $base := include "ai-optimizer.signoz.baseUrl" . -}}
{{- if ne $base "" -}}
{{- $otel := .Values.server.otel | default dict -}}
{{- $proto := include "ai-optimizer.server.otel.resolvedSignalProtocol" (dict "signalProto" $otel.tracesProtocol "genericProto" $otel.protocol) -}}
{{- $suffix := include "ai-optimizer.server.otel.signalSuffix" (dict "proto" $proto "signal" "traces" "grpcPort" (include "ai-optimizer.signoz.collectorGrpcPort" .) "httpPort" (include "ai-optimizer.signoz.collectorHttpPort" .)) -}}
{{- if ne $suffix "" -}}{{- printf "%s%s" $base $suffix -}}{{- end -}}
{{- end -}}
{{- end -}}

{{- define "ai-optimizer.server.otel.defaultLogsEndpoint" -}}
{{- $base := include "ai-optimizer.signoz.baseUrl" . -}}
{{- if ne $base "" -}}
{{- $otel := .Values.server.otel | default dict -}}
{{- $proto := include "ai-optimizer.server.otel.resolvedSignalProtocol" (dict "signalProto" $otel.logsProtocol "genericProto" $otel.protocol) -}}
{{- $suffix := include "ai-optimizer.server.otel.signalSuffix" (dict "proto" $proto "signal" "logs" "grpcPort" (include "ai-optimizer.signoz.collectorGrpcPort" .) "httpPort" (include "ai-optimizer.signoz.collectorHttpPort" .)) -}}
{{- if ne $suffix "" -}}{{- printf "%s%s" $base $suffix -}}{{- end -}}
{{- end -}}
{{- end -}}
