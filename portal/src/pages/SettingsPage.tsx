import { useState, useEffect } from "react"
import { Save, RotateCcw, CheckCircle } from "lucide-react"
import { useSettings, useUpdateSettings, useResetSettings } from "@/api/hooks"

export default function SettingsPage() {
  const { data, isLoading, error } = useSettings()
  const updateMut = useUpdateSettings()
  const resetMut = useResetSettings()
  const [values, setValues] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState(false)

  const settings: any[] = data?.data || []

  useEffect(() => {
    if (settings.length > 0 && Object.keys(values).length === 0) {
      const init: Record<string, string> = {}
      for (const s of settings) {
        init[s.name] = String(s.value)
      }
      setValues(init)
    }
  }, [settings])

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-500">Error: {(error as Error).message}</div>

  function handleSave() {
    const payload: Record<string, number> = {}
    for (const s of settings) {
      const raw = values[s.name]
      if (raw !== undefined) {
        payload[s.name] = s.type === "float" ? parseFloat(raw) : parseInt(raw, 10)
      }
    }
    updateMut.mutate(payload, {
      onSuccess: () => {
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      },
    })
  }

  function handleReset() {
    if (!confirm("Reset all settings to defaults? This cannot be undone.")) return
    resetMut.mutate(undefined, {
      onSuccess: () => {
        setValues({})
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      },
    })
  }

  const LABELS: Record<string, string> = {
    articles_per_source: "Articles per Source",
    max_total_news: "Max Total News",
    llm_call_delay: "LLM Call Delay (seconds)",
    llm_max_input_chars: "Max Input Chars",
    refresh_timeout: "Refresh Timeout (seconds)",
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">Settings</h2>
        <div className="flex gap-2">
          {saved && (
            <span className="flex items-center gap-1 text-sm text-green-600">
              <CheckCircle size={16} /> Saved
            </span>
          )}
          <button
            onClick={handleReset}
            disabled={resetMut.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            <RotateCcw size={14} />
            Reset All
          </button>
          <button
            onClick={handleSave}
            disabled={updateMut.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            <Save size={14} />
            {updateMut.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      {(updateMut.isError || resetMut.isError) && (
        <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">
          {((updateMut.error || resetMut.error) as Error)?.message}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-500">
            <tr>
              <th className="px-4 py-3 font-medium">Setting</th>
              <th className="px-4 py-3 font-medium w-48">Value</th>
              <th className="px-4 py-3 font-medium w-32">Default</th>
              <th className="px-4 py-3 font-medium w-24">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {settings.map((s: any) => (
              <tr key={s.name} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-800">{LABELS[s.name] || s.name}</div>
                  <div className="text-xs text-gray-400 mt-0.5 font-mono">{s.name}</div>
                </td>
                <td className="px-4 py-3">
                  <input
                    type="number"
                    step={s.type === "float" ? "0.1" : "1"}
                    value={values[s.name] ?? ""}
                    onChange={(e) => setValues({ ...values, [s.name]: e.target.value })}
                    className="w-full px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </td>
                <td className="px-4 py-3 text-gray-500 font-mono">{s.default}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${
                      s.source === "redis"
                        ? "bg-blue-50 text-blue-700"
                        : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {s.source}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
