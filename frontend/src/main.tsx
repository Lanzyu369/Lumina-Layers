import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installLuminaUmami, trackLuminaEvent } from './analytics/umami.ts'
import { installGlobalClientLogCapture } from './utils/clientLog.ts'

installGlobalClientLogCapture()
installLuminaUmami()
trackLuminaEvent("lumina_app_open")

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
