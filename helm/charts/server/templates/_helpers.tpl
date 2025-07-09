{{/*
Database Secret Name
*/}}
{{- define "databaseSecret" -}}
{{- $authN := .Values.database.authN | default dict }}
{{- $secretName := $authN.secretName | default "" }}
{{- if $secretName -}}
  {{- $secretName -}}
{{- else -}}
  {{- printf "%s-db-authn" (include "release.name" .) -}}
{{- end -}}
{{- end }}


{{/*
Password Generator for Databases
*/}}
{{- define "randomPassword" -}}
  {{- $minLen := 12 -}}
  {{- $maxLen := 32 -}}
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

  {{- /* Base64 encode it */ -}}
  {{- $password -}}
{{- end }}