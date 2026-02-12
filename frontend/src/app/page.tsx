'use client'

import { useEffect, useState } from 'react'

export default function Home() {
  const [apiStatus, setApiStatus] = useState<string>('checking...')

  // Use environment variable for API URL, fallback to localhost for development
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

  useEffect(() => {
    fetch(`${apiUrl}/health`)
      .then(res => res.json())
      .then(data => setApiStatus(data.status))
      .catch(() => setApiStatus('unavailable'))
  }, [apiUrl])

  return (
    <main style={{ padding: '2rem', fontFamily: 'system-ui' }}>
      <h1>Price Radar</h1>
      <p>Welcome to Price Radar - Track prices across the web</p>
      <div style={{ marginTop: '2rem' }}>
        <strong>API Status:</strong> {apiStatus}
      </div>
    </main>
  )
}
