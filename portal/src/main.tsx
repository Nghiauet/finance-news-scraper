import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter } from "react-router-dom"
import App from "./App"
import "./index.css"

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15000 } },
})

const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
