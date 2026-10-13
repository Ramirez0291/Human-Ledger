import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './i18n'
import './styles.css'
import './app.css'
import './import.css'
import './reports.css'
import './budget.css'
import './compliance.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
