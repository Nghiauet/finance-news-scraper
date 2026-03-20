import { useState } from "react"
import {
  Cpu, AlertCircle, Plus, Trash2, Zap, CheckCircle, Pencil, X, Loader2, Play,
} from "lucide-react"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts"
import {
  useAdminLlm, useAddModel, useUpdateModel, useDeleteModel,
  useActivateModel, useTestModel,
} from "@/api/hooks"
import StatsCard from "@/components/StatsCard"

interface ModelForm {
  name: string
  base_url: string
  api_key: string
  model_name: string
}

const emptyForm: ModelForm = { name: "", base_url: "", api_key: "", model_name: "" }

export default function LlmPage() {
  const { data, isLoading, error } = useAdminLlm()
  const addMut = useAddModel()
  const updateMut = useUpdateModel()
  const deleteMut = useDeleteModel()
  const activateMut = useActivateModel()
  const testMut = useTestModel()

  const [showAdd, setShowAdd] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<ModelForm>(emptyForm)
  const [testResults, setTestResults] = useState<Record<string, any>>({})

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-500">Error: {(error as Error).message}</div>

  const d = data?.data
  const model = d?.model || {}
  const totals = d?.totals || {}
  const calls: any[] = (d?.recent_calls || []).slice().reverse()
  const models: any[] = d?.models || []
  const activeModelId: string = d?.active_model_id || ""

  const chartData = calls.map((c: any, i: number) => ({
    idx: i + 1,
    prompt: c.prompt_tokens,
    completion: c.completion_tokens,
    latency: c.latency_ms,
  }))

  function handleAdd() {
    addMut.mutate(form, {
      onSuccess: () => {
        setShowAdd(false)
        setForm(emptyForm)
      },
    })
  }

  function handleUpdate() {
    if (!editId) return
    updateMut.mutate({ id: editId, ...form }, {
      onSuccess: () => {
        setEditId(null)
        setForm(emptyForm)
      },
    })
  }

  function startEdit(m: any) {
    setEditId(m.id)
    setForm({
      name: m.name || "",
      base_url: m.base_url || "",
      api_key: m.api_key || "",
      model_name: m.model_name || "",
    })
    setShowAdd(false)
  }

  function handleDelete(id: string, name: string) {
    if (!confirm(`Delete model "${name}"? This cannot be undone.`)) return
    deleteMut.mutate(id)
  }

  function handleTest(id: string) {
    setTestResults((prev) => ({ ...prev, [id]: { loading: true } }))
    testMut.mutate(id, {
      onSuccess: (data) => {
        setTestResults((prev) => ({ ...prev, [id]: data?.data }))
      },
      onError: (err) => {
        setTestResults((prev) => ({ ...prev, [id]: { ok: false, error: (err as Error).message } }))
      },
    })
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-800">LLM Usage</h2>

      {/* Models Section */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-700">Models</h3>
          <button
            onClick={() => { setShowAdd(!showAdd); setEditId(null); setForm(emptyForm) }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={14} />
            Add Model
          </button>
        </div>

        {/* Add / Edit Form */}
        {(showAdd || editId) && (
          <div className="mb-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-medium text-gray-700">
                {editId ? "Edit Model" : "Add New Model"}
              </h4>
              <button
                onClick={() => { setShowAdd(false); setEditId(null); setForm(emptyForm) }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={16} />
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Display Name</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. GPT-4o Mini"
                  className="w-full px-2.5 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Model Name</label>
                <input
                  type="text"
                  value={form.model_name}
                  onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                  placeholder="e.g. gpt-4o-mini"
                  className="w-full px-2.5 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Base URL</label>
                <input
                  type="text"
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="e.g. https://api.openai.com/v1"
                  className="w-full px-2.5 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">API Key</label>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder={editId ? "(unchanged if empty)" : "sk-..."}
                  className="w-full px-2.5 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-3">
              <button
                onClick={editId ? handleUpdate : handleAdd}
                disabled={addMut.isPending || updateMut.isPending}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {(addMut.isPending || updateMut.isPending) ? "Saving..." : editId ? "Update" : "Add"}
              </button>
              <button
                onClick={() => { setShowAdd(false); setEditId(null); setForm(emptyForm) }}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
            {(addMut.isError || updateMut.isError) && (
              <div className="mt-2 text-sm text-red-600">
                {((addMut.error || updateMut.error) as Error)?.message}
              </div>
            )}
          </div>
        )}

        {/* Model List */}
        {models.length === 0 ? (
          <div className="text-gray-400 text-sm">
            No models configured. Using environment variables ({model.model || "not set"}).
          </div>
        ) : (
          <div className="space-y-2">
            {models.map((m: any) => {
              const isActive = m.id === activeModelId
              const tr = testResults[m.id]
              return (
                <div
                  key={m.id}
                  className={`flex items-center gap-4 p-3 rounded-lg border ${
                    isActive ? "border-blue-200 bg-blue-50/50" : "border-gray-200 bg-white"
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-gray-800">{m.name}</span>
                      {isActive && (
                        <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full font-medium">
                          Active
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      {m.model_name} &middot; {m.base_url}
                    </div>
                    {m.stats && (
                      <div className="text-xs text-gray-400 mt-0.5">
                        {(m.stats.call_count || 0).toLocaleString()} calls &middot;{" "}
                        {(m.stats.total_tokens || 0).toLocaleString()} tokens
                      </div>
                    )}
                    {tr && !tr.loading && (
                      <div className={`text-xs mt-1 ${tr.ok ? "text-green-600" : "text-red-600"}`}>
                        {tr.ok
                          ? `Test OK — ${tr.latency_ms}ms`
                          : `Test failed: ${tr.error}`}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => handleTest(m.id)}
                      disabled={tr?.loading}
                      title="Test connection"
                      className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded disabled:opacity-50"
                    >
                      {tr?.loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    </button>
                    {!isActive && (
                      <button
                        onClick={() => activateMut.mutate(m.id)}
                        disabled={activateMut.isPending}
                        title="Activate"
                        className="p-1.5 text-gray-400 hover:text-green-600 hover:bg-green-50 rounded"
                      >
                        <Zap size={14} />
                      </button>
                    )}
                    <button
                      onClick={() => startEdit(m)}
                      title="Edit"
                      className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => handleDelete(m.id, m.name)}
                      disabled={deleteMut.isPending}
                      title="Delete"
                      className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Active Model Info (fallback display) */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Active Model</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
          <div>
            <span className="text-gray-400">Model</span>
            <p className="font-medium text-gray-800">{model.model || "-"}</p>
          </div>
          <div>
            <span className="text-gray-400">Base URL</span>
            <p className="font-medium text-gray-800 break-all">{model.base_url || "-"}</p>
          </div>
          <div>
            <span className="text-gray-400">Name</span>
            <p className="font-medium text-gray-800">{model.name || "-"}</p>
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard title="Total Tokens" value={(totals.total_tokens ?? 0).toLocaleString()} icon={<Cpu size={20} />} />
        <StatsCard title="Prompt Tokens" value={(totals.prompt_tokens ?? 0).toLocaleString()} icon={<Cpu size={20} />} />
        <StatsCard title="Completion Tokens" value={(totals.completion_tokens ?? 0).toLocaleString()} icon={<Cpu size={20} />} />
        <StatsCard
          title="Errors"
          value={totals.error_count ?? 0}
          icon={<AlertCircle size={20} />}
          subtitle={`${totals.call_count ?? 0} total calls`}
        />
      </div>

      {/* Token Chart */}
      {chartData.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Token Usage (Recent Calls)</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="idx" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="prompt" stackId="a" fill="#3b82f6" name="Prompt" />
              <Bar dataKey="completion" stackId="a" fill="#60a5fa" name="Completion" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent Calls Table */}
      {calls.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="p-4 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">Recent Calls ({calls.length})</h3>
          </div>
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-500 sticky top-0">
                <tr>
                  <th className="px-4 py-2 font-medium">Time</th>
                  <th className="px-4 py-2 font-medium text-right">Prompt</th>
                  <th className="px-4 py-2 font-medium text-right">Completion</th>
                  <th className="px-4 py-2 font-medium text-right">Total</th>
                  <th className="px-4 py-2 font-medium text-right">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(d?.recent_calls || []).map((c: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-500">{new Date(c.timestamp * 1000).toLocaleString("vi-VN")}</td>
                    <td className="px-4 py-2 text-right">{c.prompt_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right">{c.completion_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right font-medium">{c.total_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right text-gray-500">{(c.latency_ms / 1000).toFixed(1)}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
