import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/fira-sans/400.css'
import '@fontsource/fira-sans/500.css'
import '@fontsource/fira-sans/600.css'
import '@fontsource/fira-sans/700.css'
import '@fontsource-variable/fira-code'
import App from './App'
import './styles.css'
import { applyAccent, currentAccent } from './theme'

applyAccent(currentAccent()) // màu nhấn (mặc định xanh logo) áp ngay từ đầu cho mọi trang, kể cả trang mở đầu

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
