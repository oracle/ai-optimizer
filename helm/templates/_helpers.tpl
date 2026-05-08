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
{{- define "global.image" -}}
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
{{- define "global.imagePullSecrets" -}}
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
  {{`{{ include "global.shellWaitFunc" . | nindent 10 }}`}}
  wait_until "<label>" <max> <sleep_s> <cmd> [args...]
*********************************************** */}}
{{- define "global.shellWaitFunc" -}}
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
Validate that either client.cookieSecret or client.cookieSecretName is provided.
The cookie secret must be stable and operator-provided so Streamlit state remains
consistent across replicas. Same contract as global.api.apiKey.
*********************************************** */}}
{{- define "client.cookieKeyOrSecretName.required" -}}
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
{{- define "client.cookieSecretName" -}}
{{- $explicit := .Values.client.cookieSecretName | trim -}}
{{- if $explicit -}}{{ $explicit }}{{- else -}}{{ printf "%s-client-cookie" .Release.Name }}{{- end -}}
{{- end }}

{{- define "client.cookieSecretKey" -}}
{{- $explicit := .Values.client.cookieSecretKey | trim -}}
{{- if $explicit -}}{{ $explicit }}{{- else -}}cookieSecret{{- end -}}
{{- end }}

{{/* ******************************************
Checksum used to roll the client Deployment when the cookie-signing secret
changes. Two branches:

  * Inline path (.Values.client.cookieSecret set): hash the rendered secret.yaml.
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
{{- define "client.cookieSecretChecksum" -}}
{{- if .Values.client.cookieSecret | trim -}}
{{- include (print $.Template.BasePath "/client/secret.yaml") . | sha256sum -}}
{{- else -}}
  {{- $name := include "client.cookieSecretName" . -}}
  {{- $key := include "client.cookieSecretKey" . -}}
  {{- $found := lookup "v1" "Secret" .Release.Namespace $name -}}
  {{- if and $found $found.data (hasKey $found.data $key) -}}
{{- printf "live:%s:%s" $name (index $found.data $key) | sha256sum -}}
  {{- else -}}
{{- printf "unresolved:%s:%s" $name $key | sha256sum -}}
  {{- end -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Set the path based on baseUrlPath
Always returns a path with leading and trailing slashes for proper concatenation.
*********************************************** */}}
{{- define "global.getPath" -}}
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
{{- define "server.serviceName" -}}
{{ include "global.fullname" . }}-server-http
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
Env Secret Name Helpers
Returns either the user-provided secretName or a generated name.
*********************************************** */}}
{{- define "server.envSecretName" -}}
{{- $envSecret := .Values.server.envSecret | default dict -}}
{{- $envSecret.secretName | default (printf "%s-env" (include "global.fullname" .)) -}}
{{- end -}}

{{- define "server.envSecretKey" -}}
{{- $envSecret := .Values.server.envSecret | default dict -}}
{{- $envSecret.secretKey | default "server.env" -}}
{{- end -}}

{{- define "client.envSecretName" -}}
{{- $envSecret := .Values.client.envSecret | default dict -}}
{{- $envSecret.secretName | default (printf "%s-env" (include "global.fullname" .)) -}}
{{- end -}}

{{- define "client.envSecretKey" -}}
{{- $envSecret := .Values.client.envSecret | default dict -}}
{{- $envSecret.secretKey | default "client.env" -}}
{{- end -}}

{{- define "global.envSecretEnabled" -}}
{{- $serverEnv := .Values.server.envSecret | default dict -}}
{{- $clientEnv := .Values.client.envSecret | default dict -}}
{{- $serverContent := $serverEnv.content | default dict -}}
{{- $clientContent := $clientEnv.content | default dict -}}
{{- $serverSecretName := $serverEnv.secretName | default "" -}}
{{- $clientSecretName := $clientEnv.secretName | default "" -}}
{{- or (and (eq $serverSecretName "") (gt (len $serverContent) 0)) (and (eq $clientSecretName "") (gt (len $clientContent) 0)) -}}
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
  {{- printf "%s-db-authn" .Release.Name -}}
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
  {{- printf "%s-db-priv-authn" .Release.Name -}}
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
Validate that server.database.adb.serviceName is provided when database type is ADB-S
and no external authN secret overrides the default.
*********************************************** */}}
{{- define "server.database.validateADBSType" -}}
  {{- if eq (include "server.database.isADBS" .) "true" -}}
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
{{- define "server.database.validateOtherType" -}}
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
    {{- end -}}
  {{- end -}}
{{- end -}}

{{/* ******************************************
Validate that if server.oci_config.configMapName is specified,
then none of the other OCI config values (tenancy, user, fingerprint, region) should be provided.
*********************************************** */}}
{{- define "server.ociConfig.validate" -}}
  {{- if .Values.server.oci_config -}}
    {{- $configMapName := .Values.server.oci_config.configMapName | trim | default "" -}}
    {{- $tenancy := .Values.server.oci_config.tenancy | trim | default "" -}}
    {{- $user := .Values.server.oci_config.user | trim | default "" -}}
    {{- $fingerprint := .Values.server.oci_config.fingerprint | trim | default "" -}}
    {{- $region := .Values.server.oci_config.region | trim | default "" -}}

    {{- /* If configMapName is provided, ensure no other config values are provided */ -}}
    {{- if ne $configMapName "" -}}
      {{- if or (ne $tenancy "") (ne $user "") (ne $fingerprint "") (ne $region "") -}}
        {{- fail "server.oci_config.configMapName is specified: you cannot also provide tenancy, user, fingerprint, or region. Either provide configMapName to reference an existing ConfigMap, OR provide the config values to create a new ConfigMap." -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}


{{/* ******************************************
ADB-S Secret Name Helpers
These helpers return the secret names for ADB-S wallet/tns-admin,
supporting either existing secrets or auto-generated ones.
*********************************************** */}}
{{- define "server.database.useExistingAdbSecrets" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- default false $adb.useExisting -}}
{{- end -}}

{{- define "server.database.adbTnsAdminSecret" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- $tnsAdmin := $adb.tnsAdminSecretName | default "" -}}
{{- if ne $tnsAdmin "" -}}
  {{- $tnsAdmin -}}
{{- else -}}
  {{- printf "%s-adb-tns-admin-%d" .Release.Name .Release.Revision -}}
{{- end -}}
{{- end -}}

{{- define "server.database.adbWalletPassSecret" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- $walletPass := $adb.walletPassSecretName | default "" -}}
{{- if ne $walletPass "" -}}
  {{- $walletPass -}}
{{- else -}}
  {{- printf "%s-adb-wallet-pass-%d" .Release.Name .Release.Revision -}}
{{- end -}}
{{- end -}}

{{- define "server.database.adbWalletPassSecretKey" -}}
{{- $adb := .Values.server.database.adb | default dict -}}
{{- $walletPassKey := $adb.walletPassSecretKey | default "" -}}
{{- if ne $walletPassKey "" -}}
  {{- $walletPassKey -}}
{{- else -}}
  {{- include "server.database.adbWalletPassSecret" . -}}
{{- end -}}
{{- end -}}


{{/* ******************************************
Database Type Helpers
These helpers provide consistent database type checking across templates.
*********************************************** */}}
{{- define "server.database.type" -}}
{{- if .Values.server.database -}}
  {{- .Values.server.database.type -}}
{{- end -}}
{{- end -}}

{{- define "server.database.isSIDB" -}}
{{- eq (include "server.database.type" .) "SIDB-FREE" -}}
{{- end -}}

{{- define "server.database.isADBFree" -}}
{{- eq (include "server.database.type" .) "ADB-FREE" -}}
{{- end -}}

{{- define "server.database.isADBS" -}}
{{- eq (include "server.database.type" .) "ADB-S" -}}
{{- end -}}

{{- define "server.database.isOther" -}}
{{- eq (include "server.database.type" .) "OTHER" -}}
{{- end -}}

{{- define "server.database.isADB" -}}
{{- or (eq (include "server.database.type" .) "ADB-S") (eq (include "server.database.type" .) "ADB-FREE") -}}
{{- end -}}

{{- define "server.database.isContainerDB" -}}
{{- or (eq (include "server.database.type" .) "SIDB-FREE") (eq (include "server.database.type" .) "ADB-FREE") -}}
{{- end -}}

{{- define "server.database.needsPrivAuth" -}}
{{- or (eq (include "server.database.isADB" .) "true") (eq (include "server.database.isOther" .) "true") -}}
{{- end -}}

{{/* ******************************************
Database Service Name Helper
Returns the short database type prefix (sidb or adb) for service naming.
*********************************************** */}}
{{- define "server.database.dbName" -}}
{{- $dbType := include "server.database.type" . -}}
{{- if $dbType -}}
  {{- lower (split "-" $dbType)._0 -}}
{{- end -}}
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
{{- define "server.otel.resourceAttributes" -}}
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
log-export gating; comments next to each check spell out which silent
failure mode that check defends against.
*********************************************** */}}
{{- define "server.otel.validate" -}}
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
    {{- $signozEnabled := ne (include "signoz.baseUrl" .) "" -}}
    {{- $signozTracesEp := include "server.otel.defaultTracesEndpoint" . -}}
    {{- $signozLogsEp := include "server.otel.defaultLogsEndpoint" . -}}

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
        {{- fail (printf "server.otel.tracesExporter contains unsupported token %q. Supported tokens: \"otlp\", \"console\", \"none\". The application would silently drop this token at runtime." $tok) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Edge case: input was entirely empty / whitespace-only tokens
           (e.g. ",,, "). Per-token loop above accepts each as a skip,
           leaving $supported empty. */ -}}
    {{- if eq (len $supported) 0 -}}
      {{- fail (printf "server.otel.tracesExporter=%q has no supported entries (use \"otlp\", \"console\", \"none\", or a comma-separated mix). The application would silently produce no telemetry." (trim $rawExporter)) -}}
    {{- end -}}

    {{- /* "none" is the documented opt-out sentinel and must be the ONLY
           token. The application's exporter-set intersection silently
           drops "none" when mixed with "otlp" or "console", so a list
           like "none,otlp" still ships traces — defeating the operator's
           intent. Reject mixed lists rather than silently honoring (or
           silently ignoring) half of the user's input. */ -}}
    {{- if and (has "none" $supported) (gt (len ($supported | uniq)) 1) -}}
      {{- fail "server.otel.tracesExporter: \"none\" is the opt-out sentinel and must be the only token. The application's exporter intersection silently drops \"none\" when mixed with other tokens; use \"none\" alone to disable, or list only \"otlp\"/\"console\"." -}}
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
        {{- fail "server.otel: tracesExporter includes \"otlp\" and signoz.enabled=true, but the SigNoz collector port for the resolved traces protocol is disabled. Re-enable signoz.otelCollector.ports.otlp.enabled (or otlp-http.enabled if using http/protobuf), switch protocols, or set server.otel.endpoint / tracesEndpoint explicitly." -}}
      {{- else -}}
        {{- fail "server.otel: tracesExporter includes \"otlp\" but no endpoint is configured. Set server.otel.endpoint or server.otel.tracesEndpoint, enable signoz.enabled to use the in-chart collector, or set tracesExporter=\"console\" for local-only debugging." -}}
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
        {{- fail (printf "server.otel.%s=%q is not a supported OTLP protocol. Use \"grpc\" (port 4317) or \"http/protobuf\" (port 4318); empty falls back to the SDK default of grpc." $field (toString $val)) -}}
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
        {{- fail (printf "server.otel.logsExporter contains unsupported token %q. This application's log exporter supports only \"otlp\" or \"none\"." $tok) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Same opt-out rule as tracesExporter: "none" must be alone. For
           logs the app DOES honor mixed-"none" at runtime, but a chart
           that accepts "otlp,none" while the sibling tracesExporter
           rejects it is more confusing than one consistent rule.
           Operators learn one thing: "none" stands alone, on either field. */ -}}
    {{- if and $hasNoneLogs $hasOtlpLogs -}}
      {{- fail "server.otel.logsExporter: \"none\" is the opt-out sentinel and must be the only token. Use \"none\" alone to suppress log export, or \"otlp\" alone to ship logs." -}}
    {{- end -}}

    {{- /* logsEndpoint without OTLP in traces is wasted configuration: the
           application activates log export only when OTLP traces attach.
           Skipped when the user has explicitly opted out via "none" — the
           wasted-config concern is moot because the app ignores the endpoint. */ -}}
    {{- if and (ne $logsEp "") (not (has "otlp" $supported)) (not $hasNoneLogs) -}}
      {{- fail "server.otel.logsEndpoint is set but tracesExporter does not include \"otlp\"; the application activates log export only when OTLP traces are also active. Add \"otlp\" to tracesExporter, set logsExporter=\"none\" to acknowledge the opt-out, or remove logsEndpoint." -}}
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
        {{- fail "server.otel.logsEnabled is true but tracesExporter does not include \"otlp\"; the application gates log export on OTLP traces being active. Either include \"otlp\" in tracesExporter (and set an endpoint), set logsExporter=\"none\" to opt out of log export, or disable logsEnabled." -}}
      {{- end -}}
      {{- if and (eq $endpoint "") (eq $logsEp "") (eq $signozLogsEp "") -}}
        {{- if and $signozEnabled -}}
          {{- fail "server.otel.logsEnabled is true and signoz.enabled=true, but the SigNoz collector port for the resolved logs protocol is disabled. Re-enable signoz.otelCollector.ports.otlp.enabled (or otlp-http.enabled if using http/protobuf), switch protocols, set server.otel.endpoint / logsEndpoint explicitly, set logsExporter=\"none\" to opt out, or disable logsEnabled." -}}
        {{- else -}}
          {{- fail "server.otel.logsEnabled is true but no log endpoint is reachable. Set server.otel.endpoint (generic, used by both signals) or server.otel.logsEndpoint, enable signoz.enabled to use the in-chart collector, set logsExporter=\"none\" to opt out, or disable logsEnabled. server.otel.tracesEndpoint alone activates only traces; the application's log exporter does not read it." -}}
        {{- end -}}
      {{- end -}}
      {{- if and (ne $rawLogsExporter "") (not $hasOtlpLogs) -}}
        {{- fail (printf "server.otel.logsEnabled is true but logsExporter=%q would silently drop logs at runtime. Use \"otlp\" to ship logs, \"none\" to explicitly suppress them, drop the value to take the default, or disable logsEnabled." $rawLogsExporter) -}}
      {{- end -}}
    {{- end -}}

    {{- /* Plaintext headers vs Secret-sourced headers are mutually exclusive. */ -}}
    {{- $headers := $otel.headers | default "" | trim -}}
    {{- $headersSecret := $otel.headersSecret | default dict -}}
    {{- $headersSecretName := $headersSecret.name | default "" | trim -}}
    {{- if and (ne $headers "") (ne $headersSecretName "") -}}
      {{- fail "server.otel: cannot set both `headers` (plaintext) and `headersSecret.name`. Choose one." -}}
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
{{- define "signoz.releaseFullname" -}}
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

{{- /* Schemeful base URL of the in-cluster collector, no port. Returns "" when
       signoz.enabled is false. Used both as a "is the auto-default available?"
       sentinel in validation and as the building block for the per-signal
       endpoint helpers below.

       Form is `<svc>.<ns>.svc` rather than `<svc>.<ns>.svc.cluster.local`
       — pods receive a search domain that expands `.svc` to the cluster's
       configured DNS suffix automatically, so this works on any cluster
       (including those with non-default cluster domains) without a
       chart-side `clusterDomain` knob. */ -}}
{{- define "signoz.baseUrl" -}}
{{- $base := include "signoz.releaseFullname" . -}}
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
{{- define "signoz.authnSecretName" -}}
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
{{- define "signoz.rootProvisioningEnabled" -}}
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
{{- define "signoz.frontendPort" -}}
{{- dig "signoz" "service" "port" 8080 (.Values.signoz | default dict) -}}
{{- end -}}


{{- /* Schemeful URL of the in-cluster SigNoz frontend (the dashboards/rules
       API the setup Job talks to), with port. Mirrors `signoz.baseUrl` but
       targets the frontend service rather than the otel-collector service.
       Returns "" when signoz.enabled is false so callers can gate. */ -}}
{{- define "signoz.frontendUrl" -}}
{{- $base := include "signoz.releaseFullname" . -}}
{{- if ne $base "" -}}
{{- printf "http://%s.%s.svc:%v" $base .Release.Namespace (include "signoz.frontendPort" .) -}}
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
{{- define "signoz.collectorGrpcPort" -}}
{{- $otlp := dig "otelCollector" "ports" "otlp" (dict) (.Values.signoz | default dict) -}}
{{- if and $otlp $otlp.enabled -}}
{{- default 4317 $otlp.servicePort -}}
{{- end -}}
{{- end -}}

{{- define "signoz.collectorHttpPort" -}}
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
{{- define "server.otel.resolvedSignalProtocol" -}}
{{- /* Caller passes {signalProto, genericProto}. Returns the trimmed
       lowercased protocol the SDK will use for that signal. */ -}}
{{- $signal := trim (default "" .signalProto | toString) -}}
{{- $generic := trim (default "" .genericProto | toString) -}}
{{- if ne $signal "" -}}{{ lower $signal }}{{- else -}}{{ lower $generic }}{{- end -}}
{{- end -}}

{{- define "server.otel.signalSuffix" -}}
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
{{- define "server.otel.defaultTracesEndpoint" -}}
{{- $base := include "signoz.baseUrl" . -}}
{{- if ne $base "" -}}
{{- $otel := .Values.server.otel | default dict -}}
{{- $proto := include "server.otel.resolvedSignalProtocol" (dict "signalProto" $otel.tracesProtocol "genericProto" $otel.protocol) -}}
{{- $suffix := include "server.otel.signalSuffix" (dict "proto" $proto "signal" "traces" "grpcPort" (include "signoz.collectorGrpcPort" .) "httpPort" (include "signoz.collectorHttpPort" .)) -}}
{{- if ne $suffix "" -}}{{- printf "%s%s" $base $suffix -}}{{- end -}}
{{- end -}}
{{- end -}}

{{- define "server.otel.defaultLogsEndpoint" -}}
{{- $base := include "signoz.baseUrl" . -}}
{{- if ne $base "" -}}
{{- $otel := .Values.server.otel | default dict -}}
{{- $proto := include "server.otel.resolvedSignalProtocol" (dict "signalProto" $otel.logsProtocol "genericProto" $otel.protocol) -}}
{{- $suffix := include "server.otel.signalSuffix" (dict "proto" $proto "signal" "logs" "grpcPort" (include "signoz.collectorGrpcPort" .) "httpPort" (include "signoz.collectorHttpPort" .)) -}}
{{- if ne $suffix "" -}}{{- printf "%s%s" $base $suffix -}}{{- end -}}
{{- end -}}
{{- end -}}
