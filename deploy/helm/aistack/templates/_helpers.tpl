{{- define "aistack.labels" -}}
app.kubernetes.io/name: aistack
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "aistack.selector" -}}
app.kubernetes.io/name: aistack
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .c }}
{{- end -}}

{{- define "aistack.issuer" -}}
{{- if .Values.config.oidcIssuer -}}{{ .Values.config.oidcIssuer }}{{- else -}}{{ .Values.publicApiUrl }}/idp{{- end -}}
{{- end -}}

{{- define "aistack.securityContext" -}}
runAsNonRoot: true
runAsUser: 10001
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
seccompProfile:
  type: RuntimeDefault
{{- end -}}
