import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'

const authEnabled = import.meta.env.VITE_AUTH_ENABLED === 'true'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider enabled={authEnabled}>
      <App />
    </AuthProvider>
  </StrictMode>,
)
