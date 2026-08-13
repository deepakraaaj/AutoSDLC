import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './styles/base.css'
import './styles/primitives.css'
import App from './App.tsx'
import { ToastProvider } from './hooks/useToast.tsx'
import { RoleProvider } from './hooks/useRole.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <ToastProvider>
        <RoleProvider>
          <App />
        </RoleProvider>
      </ToastProvider>
    </ErrorBoundary>
  </StrictMode>,
)
