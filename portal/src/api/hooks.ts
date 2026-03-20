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

export function useNewsList(source?: string, limit = 20, cursor?: string) {
  const params = new URLSearchParams()
  if (source) params.set("source", source)
  params.set("limit", String(limit))
  if (cursor) params.set("cursor", cursor)
  const qs = params.toString()

  return useQuery({
    queryKey: ["news", source, limit, cursor],
    queryFn: () => apiFetch<any>(`/news?${qs}`),
  })
}

export function useNewsDetail(id: string) {
  return useQuery({
    queryKey: ["news", id],
    queryFn: () => apiFetch<any>(`/news/${id}`),
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

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (settings: Record<string, number>) => apiPut<any>("/admin/settings", settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "settings"] })
    },
  })
}

export function useResetSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<any>("/admin/settings/reset"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "settings"] })
    },
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
