import { Routes, Route } from "react-router-dom"
import Layout from "./components/Layout"
import AuthGuard from "./components/AuthGuard"
import LoginPage from "./pages/LoginPage"
import DashboardPage from "./pages/DashboardPage"
import NewsPage from "./pages/NewsPage"
import ArticlePage from "./pages/ArticlePage"
import LlmPage from "./pages/LlmPage"
import CachePage from "./pages/CachePage"
import SettingsPage from "./pages/SettingsPage"

export default function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<AuthGuard />}>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="news" element={<NewsPage />} />
          <Route path="news/:id" element={<ArticlePage />} />
          <Route path="llm" element={<LlmPage />} />
          <Route path="cache" element={<CachePage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
