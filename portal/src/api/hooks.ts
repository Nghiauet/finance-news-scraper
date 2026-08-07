import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch, apiPost, apiPut, apiDelete } from "./client"

// ---------- Existing hooks ----------

export function useAdminStats() {
  return useQuery({
    queryKey: ["admin", "stats"],
    queryFn: () => apiFetch<any>("/admin/stats"),
    refetchInterval: 30000,
  })
}

export function useAdminLlm() {
  return useQuery({
    queryKey: ["admin", "llm"],
    queryFn: () => apiFetch<any>("/admin/llm"),
    refetchInterval: 30000,
  })
}

export function useAdminSources() {
  return useQuery({
    queryKey: ["admin", "sources"],
    queryFn: () => apiFetch<any>("/admin/sources"),
    refetchInterval: 30000,
  })
}

export function useAdminCache() {
  return useQuery({
    queryKey: ["admin", "cache"],
    queryFn: () => apiFetch<any>("/admin/cache"),
    refetchInterval: 30000,
  })
}

export type Language = "vi" | "en"

export function useNewsList(
  source?: string,
  limit = 20,
  cursor?: string,
  sort = "newest",
  q?: string,
  language: Language = "vi",
) {
  const params = new URLSearchParams()
  if (source) params.set("source", source)
  params.set("limit", String(limit))
  if (cursor) params.set("cursor", cursor)
  if (sort) params.set("sort", sort)
  if (q) params.set("q", q)
  if (language && language !== "vi") params.set("language", language)
  const qs = params.toString()

  return useQuery({
    queryKey: ["news", source, limit, cursor, sort, q, language],
    queryFn: () => apiFetch<any>(`/news?${qs}`),
  })
}

export function useNewsDetail(id: string, language: Language = "vi") {
  const qs = language !== "vi" ? `?language=${language}` : ""
  return useQuery({
    queryKey: ["news", id, language],
    queryFn: () => apiFetch<any>(`/news/${id}${qs}`),
    enabled: !!id,
  })
}

// ---------- Settings hooks ----------

export function useSettings() {
  return useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => apiFetch<any>("/admin/settings"),
  })
}

// Both endpoints return the full settings list, so write it straight into the
// cache. Invalidating instead left a window where the form still showed the old
// values while the refetch was in flight.
export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (settings: Record<string, number>) => apiPut<any>("/admin/settings", settings),
    onSuccess: (resp) => qc.setQueryData(["admin", "settings"], resp),
  })
}

export function useResetSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<any>("/admin/settings/reset"),
    onSuccess: (resp) => qc.setQueryData(["admin", "settings"], resp),
  })
}

// ---------- Model hooks ----------

export function useModels() {
  return useQuery({
    queryKey: ["admin", "models"],
    queryFn: () => apiFetch<any>("/admin/models"),
    refetchInterval: 30000,
  })
}

export function useAddModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (model: { name: string; base_url: string; api_key: string; model_name: string }) =>
      apiPost<any>("/admin/models", model),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "models"] })
      qc.invalidateQueries({ queryKey: ["admin", "llm"] })
    },
  })
}

export function useUpdateModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...config }: { id: string; name?: string; base_url?: string; api_key?: string; model_name?: string }) =>
      apiPut<any>(`/admin/models/${id}`, config),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "models"] })
      qc.invalidateQueries({ queryKey: ["admin", "llm"] })
    },
  })
}

export function useDeleteModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete<any>(`/admin/models/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "models"] })
      qc.invalidateQueries({ queryKey: ["admin", "llm"] })
    },
  })
}

export function useActivateModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost<any>(`/admin/models/${id}/activate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "models"] })
      qc.invalidateQueries({ queryKey: ["admin", "llm"] })
    },
  })
}

export function useTestModel() {
  return useMutation({
    mutationFn: (id: string) => apiPost<any>(`/admin/models/${id}/test`),
  })
}

// ---------- Monitoring hooks ----------

export function useAdminCron() {
  return useQuery({
    queryKey: ["admin", "cron"],
    queryFn: () => apiFetch<any>("/admin/cron"),
    refetchInterval: 30000,
  })
}

export function useAdminErrors(hours = 24) {
  return useQuery({
    queryKey: ["admin", "errors", hours],
    queryFn: () => apiFetch<any>(`/admin/errors?hours=${hours}`),
    refetchInterval: 30000,
  })
}

export function useRefreshAll() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<any>("/admin/refresh-all"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "cron"] })
      qc.invalidateQueries({ queryKey: ["admin", "stats"] })
      qc.invalidateQueries({ queryKey: ["news"] })
    },
  })
}

export function useRefreshStatus() {
  return useQuery({
    queryKey: ["admin", "refresh-status"],
    queryFn: () => apiFetch<any>("/admin/refresh-status"),
    refetchInterval: 5000,
  })
}

export function usePurgeCache() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<any>("/admin/purge"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "stats"] })
      qc.invalidateQueries({ queryKey: ["admin", "cache"] })
      qc.invalidateQueries({ queryKey: ["admin", "cron"] })
      qc.invalidateQueries({ queryKey: ["news"] })
    },
  })
}

// ---------- Preview hooks ----------

export function usePreviewScrape() {
  return useMutation({
    mutationFn: ({ source, limit }: { source: string; limit: number }) =>
      apiPost<any>(`/admin/preview/${source}?limit=${limit}`),
  })
}

export function useRefreshSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (source: string) => apiPost<any>(`/admin/refresh/${source}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "stats"] })
      qc.invalidateQueries({ queryKey: ["admin", "sources"] })
      qc.invalidateQueries({ queryKey: ["news"] })
    },
  })
}
