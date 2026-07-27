import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { PostMyPostProjectProvider } from './context/PostMyPostProjectContext'
import { TelegramProvider } from './context/TelegramContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <TelegramProvider>
      <PostMyPostProjectProvider>
        <App />
      </PostMyPostProjectProvider>
    </TelegramProvider>
  </React.StrictMode>,
)
