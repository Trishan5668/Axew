import { Navigate } from 'react-router-dom'

export function OAuthCallbackPage(): JSX.Element {
  return <Navigate to="/login" replace />
}
