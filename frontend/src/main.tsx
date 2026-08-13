import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import '@mantine/core/styles.css'
import App from './App'
import { apexTheme } from './theme'
import './styles/globals.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={apexTheme} forceColorScheme="dark">
      <App />
    </MantineProvider>
  </React.StrictMode>
)
