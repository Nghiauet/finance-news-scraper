import { Navigate, Outlet } from "react-router-dom"
import { isAuthenticated } from "@/api/auth"

export default function AuthGuard() {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}
